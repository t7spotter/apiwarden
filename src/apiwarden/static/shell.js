/* Shell behaviour, shared by the RapiDoc pages and the plain ones.

   Three jobs: move between APIs, search across all of them, and apply live
   updates. On a RapiDoc page an update is pushed straight into the element
   with loadSpec(), so the reader keeps their scroll position instead of
   watching the page reload underneath them. */

(function () {
  var config = window.APIWARDEN || {};
  var base = config.base || "";
  var docs = document.getElementById("docs");

  function url(path) {
    return base + "/" + String(path).replace(/^\//, "");
  }

  function escapeHtml(value) {
    var div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
  }

  /* ---------- changelog times ---------- */

  // The server writes UTC; show the reader's own clock, plus how long ago.
  function ago(then) {
    var seconds = Math.max(0, (Date.now() - then) / 1000);
    var steps = [[60, "second"], [60, "minute"], [24, "hour"], [30, "day"], [12, "month"], [Infinity, "year"]];
    for (var i = 0; i < steps.length; i++) {
      if (seconds < steps[i][0]) {
        var n = Math.floor(seconds);
        return i === 0 ? "just now" : n + " " + steps[i][1] + (n === 1 ? "" : "s") + " ago";
      }
      seconds /= steps[i][0];
    }
  }

  Array.prototype.forEach.call(document.querySelectorAll("time.entry-time, time.since-time"), function (node) {
    var then = new Date(node.getAttribute("datetime"));
    if (isNaN(then)) return;
    node.textContent = then.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
    if (!node.classList.contains("entry-time")) return;
    var hint = document.createElement("span");
    hint.className = "entry-ago";
    hint.textContent = ago(then.getTime());
    node.appendChild(hint);
  });

  /* ---------- switch between APIs ---------- */

  var switcher = document.getElementById("api-switch");
  if (switcher) {
    switcher.addEventListener("change", function () {
      if (switcher.value) location.href = switcher.value;
    });
  }

  /* ---------- search across every spec ---------- */

  var input = document.getElementById("search-input");
  var results = document.getElementById("search-results");

  if (input && results) {
    var operations = null;

    function loadIndex() {
      if (operations) return Promise.resolve(operations);
      return fetch(url("index.json"))
        .then(function (response) {
          return response.json();
        })
        .then(function (payload) {
          operations = payload.operations || [];
          return operations;
        })
        .catch(function () {
          operations = [];
          return operations;
        });
    }

    function score(operation, terms) {
      var fields = [
        [operation.id.toLowerCase(), 6],
        [operation.path.toLowerCase(), 5],
        [(operation.summary || "").toLowerCase(), 4],
        [(operation.tags || []).join(" ").toLowerCase(), 3],
        [operation.app.toLowerCase(), 2],
      ];
      var total = 0;
      fields.forEach(function (field) {
        terms.forEach(function (term) {
          if (field[0].indexOf(term) !== -1) total += field[1];
        });
      });
      return total;
    }

    function render(matches) {
      results.innerHTML = "";
      if (!matches.length) {
        results.innerHTML = '<li class="search-empty">No matching operation.</li>';
        return;
      }
      matches.forEach(function (operation) {
        var li = document.createElement("li");
        var link = document.createElement("a");
        // Same API: jump within the rendered page. Different API: navigate.
        link.href =
          url(encodeURIComponent(operation.app) + "/") +
          "?op=" +
          encodeURIComponent(operation.method + " " + operation.path);
        link.innerHTML =
          "<strong>" + escapeHtml(operation.method) + "</strong> " +
          escapeHtml(operation.summary || operation.id) +
          '<span class="sr-path">' + escapeHtml(operation.path) + " · " + escapeHtml(operation.app) + "</span>";

        if (operation.app === config.app) {
          link.addEventListener("click", function (event) {
            event.preventDefault();
            goToOperation(operation.method, operation.path);
            results.innerHTML = "";
            input.value = "";
          });
        }
        li.appendChild(link);
        results.appendChild(li);
      });
    }

    var timer = null;
    input.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        var query = input.value.trim().toLowerCase();
        if (!query) {
          results.innerHTML = "";
          return;
        }
        var terms = query.split(/\s+/);
        loadIndex().then(function (all) {
          render(
            all
              .map(function (operation) {
                return { operation: operation, score: score(operation, terms) };
              })
              .filter(function (row) {
                return row.score > 0;
              })
              .sort(function (a, b) {
                return b.score - a.score;
              })
              .slice(0, 12)
              .map(function (row) {
                return row.operation;
              })
          );
        });
      }, 90);
    });

    document.addEventListener("click", function (event) {
      if (!results.contains(event.target) && event.target !== input) results.innerHTML = "";
    });
  }

  /* ---------- what changed since the reader's last visit ----------

     The changelog already records every contract change with a timestamp. The
     only thing kept per reader is the newest timestamp they have seen, in
     localStorage like the token — so there is nothing to configure and the
     server stays stateless. The first visit sees nothing as new; opening the
     Changes page, or "Mark as seen", moves the line forward. */

  var SEEN_KEY = "apiwarden:seen:" + base;
  var LEVELS = ["breaking", "additive", "info"];
  var newsSheet = null;
  var newestAt = 0;

  function readSeen() {
    try {
      var raw = localStorage.getItem(SEEN_KEY);
      return raw === null ? null : parseFloat(raw);
    } catch (e) {
      return null;
    }
  }

  function writeSeen(at) {
    try {
      localStorage.setItem(SEEN_KEY, String(at));
    } catch (e) {
      // Markers simply reappear on the next page; nothing is lost.
    }
  }

  function worstOf(a, b) {
    return LEVELS.indexOf(a) <= LEVELS.indexOf(b) ? a : b;
  }

  // Group unseen changes by operation: {"tasks|GET /tasks/": "additive", ...}
  function summariseNews(entries) {
    var seen = {};
    entries.forEach(function (entry) {
      (entry.changes || []).forEach(function (change) {
        var key = change.app + "|" + (change.operation || "");
        seen[key] = key in seen ? worstOf(seen[key], change.level) : change.level;
      });
    });
    return seen;
  }

  function cssString(value) {
    return '"' + String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"';
  }

  // RapiDoc's nav lives in a shadow root, so the markers are a stylesheet
  // adopted into it. It survives the renderer re-rendering its own nav.
  function markNav(grouped) {
    if (!docs || !config.app) return;
    var colours = { breaking: "#d13438", additive: "#2e8b57", info: "#8a8f98" };
    var rules = Object.keys(grouped)
      .map(function (key) {
        var split = key.indexOf("|");
        var app = key.slice(0, split);
        var operation = key.slice(split + 1);
        var parts = operation.split(" ");
        if (app !== config.app || parts.length !== 2) return "";
        // The same id RapiDoc gives the nav item; see goToOperation() below.
        var id = parts[0].toLowerCase() + "-" + parts[1].replace(/[\s#:?&={}]/g, "-");
        return (
          '.nav-bar-path[data-content-id=' + cssString(id) + ']{position:relative;padding-inline-end:26px !important}' +
          '.nav-bar-path[data-content-id=' + cssString(id) + ']::after{content:"";position:absolute;' +
          "inset-inline-end:10px;inset-block-start:50%;width:8px;height:8px;margin-top:-4px;" +
          "border-radius:50%;background:" + colours[grouped[key]] + "}"
        );
      })
      .join("");

    customElements.whenDefined("rapi-doc").then(function () {
      var root = docs.shadowRoot;
      if (!root) return;
      if (typeof CSSStyleSheet === "function" && "adoptedStyleSheets" in root) {
        if (!newsSheet) {
          newsSheet = new CSSStyleSheet();
          root.adoptedStyleSheets = root.adoptedStyleSheets.concat([newsSheet]);
        }
        newsSheet.replaceSync(rules);
      } else {
        var style = root.getElementById("apiwarden-news") || document.createElement("style");
        style.id = "apiwarden-news";
        style.textContent = rules;
        root.appendChild(style);
      }
    });
  }

  function clearNews() {
    Array.prototype.forEach.call(document.querySelectorAll(".news-count"), function (badge) {
      badge.hidden = true;
    });
    var line = document.getElementById("portal-news");
    if (line) line.hidden = true;
    Array.prototype.forEach.call(document.querySelectorAll("#api-switch option[data-app]"), function (option) {
      if (option.dataset.label) option.textContent = option.dataset.label;
    });
    Array.prototype.forEach.call(document.querySelectorAll(".card .pill-new"), function (pill) {
      pill.remove();
    });
    markNav({});
  }

  function showNews(fresh) {
    var grouped = summariseNews(fresh);
    var keys = Object.keys(grouped);
    if (!keys.length) return clearNews();

    var worst = keys.reduce(function (level, key) {
      return worstOf(level, grouped[key]);
    }, "info");
    var label = keys.length + (keys.length === 1 ? " change" : " changes");

    Array.prototype.forEach.call(document.querySelectorAll(".news-count"), function (badge) {
      badge.textContent = String(keys.length);
      badge.className = "news-count level-" + worst;
      badge.title = label + " since your last visit";
      badge.hidden = false;
    });

    var line = document.getElementById("portal-news");
    if (line) {
      document.getElementById("news-text").textContent = label + " since your last visit";
      line.hidden = false;
    }

    // Per API: how many, and how bad, so the switcher and the cards point at it.
    var perApp = {};
    keys.forEach(function (key) {
      var app = key.slice(0, key.indexOf("|"));
      var entry = perApp[app] || (perApp[app] = { count: 0, worst: "info" });
      entry.count += 1;
      entry.worst = worstOf(entry.worst, grouped[key]);
    });

    Array.prototype.forEach.call(document.querySelectorAll("#api-switch option[data-app]"), function (option) {
      if (!option.dataset.label) option.dataset.label = option.textContent;
      var hit = perApp[option.dataset.app];
      option.textContent = hit ? option.dataset.label + "  \u00b7 " + hit.count + " new" : option.dataset.label;
    });

    Array.prototype.forEach.call(document.querySelectorAll("a.card[data-app]"), function (card) {
      var hit = perApp[card.getAttribute("data-app")];
      var old = card.querySelector(".pill-new");
      if (old) old.remove();
      if (!hit) return;
      var pill = document.createElement("span");
      pill.className = "pill pill-new pill-" + hit.worst;
      pill.textContent = hit.count + " new";
      card.appendChild(document.createTextNode(" "));
      card.appendChild(pill);
    });

    markNav(grouped);
  }

  // On the Changes page itself, point at the entries that are new, then treat
  // them as seen: the reader is looking at them now.
  function highlightEntries(seen) {
    Array.prototype.forEach.call(document.querySelectorAll(".changelog .entry[data-at]"), function (entry) {
      if (parseFloat(entry.getAttribute("data-at")) <= seen) return;
      entry.classList.add("entry-new");
      var tag = document.createElement("span");
      tag.className = "entry-new-tag";
      tag.textContent = "New";
      entry.querySelector("summary").insertBefore(tag, entry.querySelector("summary").firstChild);
    });
  }

  function loadNews() {
    if (typeof fetch !== "function") return;
    fetch(url("changes.json"), { credentials: "same-origin" })
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (data) {
        if (!data || !data.entries) return;
        newestAt = data.entries.length ? data.entries[0].at : 0;

        var seen = readSeen();
        if (seen === null) {
          // First visit: everything up to now is background, not news.
          seen = newestAt;
          writeSeen(seen);
        }

        if (document.querySelector(".changelog")) {
          highlightEntries(seen);
          writeSeen(Math.max(seen, newestAt));
          clearNews();
          return;
        }
        showNews(
          data.entries.filter(function (entry) {
            return entry.at > seen;
          })
        );
      })
      .catch(function () {
        // A gated or offline portal just shows no markers.
      });
  }

  var seenButton = document.getElementById("news-seen");
  if (seenButton) {
    seenButton.addEventListener("click", function () {
      writeSeen(Math.max(readSeen() || 0, newestAt));
      clearNews();
    });
  }

  loadNews();

  /* ---------- examples under "Compare against a specific version" ---------- */

  Array.prototype.forEach.call(document.querySelectorAll(".since-example"), function (button) {
    button.addEventListener("click", function () {
      var field = document.getElementById("since");
      if (!field) return;
      field.value = button.getAttribute("data-example");
      field.focus();
    });
  });

  /* ---------- global bearer token, applied to every API's Try it panel ----------

     Lives in localStorage only — never sent to or read by this server — so it
     survives switching APIs (a real page navigation) without being re-entered.
     Present on every page, not just RapiDoc ones, so it can be set before the
     reader has even opened a spec. Namespaced by base path so two apiwarden
     mounts on the same origin don't share a token. */

  var TOKEN_KEY = "apiwarden:token:" + base;
  var tokenInput = document.getElementById("auth-token");
  var tokenClear = document.getElementById("auth-token-clear");

  function readToken() {
    try {
      return localStorage.getItem(TOKEN_KEY) || "";
    } catch (e) {
      return ""; // private browsing, or storage blocked entirely
    }
  }

  function writeToken(value) {
    try {
      if (value) localStorage.setItem(TOKEN_KEY, value);
      else localStorage.removeItem(TOKEN_KEY);
    } catch (e) {
      // The field still works for this page load; it just won't carry over.
    }
  }

  function applyToken() {
    if (!docs || typeof docs.setApiKey !== "function") return;
    var token = readToken();
    if (!token) return;
    var schemes = (docs.resolvedSpec && docs.resolvedSpec.securitySchemes) || [];
    schemes.forEach(function (scheme) {
      // Basic auth needs a username and password, not one token — skip it.
      if (scheme.type === "http" && scheme.scheme === "basic") return;
      docs.setApiKey(scheme.securitySchemeId, token);
    });
  }

  if (tokenInput) {
    tokenInput.value = readToken();
    var tokenTimer = null;
    tokenInput.addEventListener("input", function () {
      clearTimeout(tokenTimer);
      tokenTimer = setTimeout(function () {
        writeToken(tokenInput.value.trim());
        applyToken();
      }, 200);
    });
  }

  if (tokenClear) {
    tokenClear.addEventListener("click", function () {
      writeToken("");
      if (tokenInput) tokenInput.value = "";
      if (docs && typeof docs.removeAllSecurityKeys === "function") {
        docs.removeAllSecurityKeys();
      }
    });
  }

  /* ---------- the RapiDoc element ---------- */

  if (!docs) return;
  docs.addEventListener("spec-loaded", applyToken);

  function applyTheme() {
    if (config.theme !== "auto") return;
    var dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    var palette = dark
      ? { theme: "dark", bg: "#1e1e1e", text: "#d4d4d4", nav: "#252526", navText: "#bbbbbb", hover: "#37373d", accent: "#4daafc" }
      : { theme: "light", bg: "#ffffff", text: "#1a1d21", nav: "#f3f3f3", navText: "#3b4048", hover: "#e4e6e9", accent: "#0066b8" };

    docs.setAttribute("theme", palette.theme);
    docs.setAttribute("bg-color", palette.bg);
    docs.setAttribute("text-color", palette.text);
    docs.setAttribute("nav-bg-color", palette.nav);
    docs.setAttribute("nav-text-color", palette.navText);
    docs.setAttribute("nav-hover-bg-color", palette.hover);
    docs.setAttribute("nav-accent-color", palette.accent);
    docs.setAttribute("primary-color", palette.accent);
    document.body.style.background = palette.bg;
  }

  applyTheme();
  if (config.theme === "auto" && window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyTheme);
  }

  function goToOperation(method, path) {
    // RapiDoc builds an operation's element id as `<method>-<path>`, replacing
    // only [\s#:?&={}] with hyphens — slashes survive. See spec-parser.js.
    var slug = path.replace(/[\s#:?&={}]/g, "-");
    if (typeof docs.scrollToPath === "function") {
      docs.scrollToPath(method.toLowerCase() + "-" + slug);
    }
  }

  function pendingOperation() {
    var wanted = new URLSearchParams(location.search).get("op");
    if (!wanted) return;
    var parts = wanted.split(" ");
    if (parts.length === 2) goToOperation(parts[0], parts[1]);
  }

  docs.addEventListener("spec-loaded", function () {
    // The nav is only built once the spec is in, so deep links wait for it.
    setTimeout(pendingOperation, 60);
  });

  /* ---------- draggable edge on RapiDoc's left nav ----------

     RapiDoc fixes the nav's width in its own stylesheet. A thin handle is laid
     over the nav's right edge in this document; dragging it sets a custom
     property on <rapi-doc>, which rapidoc-extra.css applies to the nav. The
     width is remembered per base path. Double-click (or Home) resets it. */

  var NAV_KEY = "apiwarden:navwidth:" + base;
  var NAV_MIN = 220;
  var splitter = document.createElement("div");
  splitter.className = "nav-splitter";
  splitter.setAttribute("role", "separator");
  splitter.setAttribute("aria-orientation", "vertical");
  splitter.setAttribute("aria-label", "Resize the navigation (arrow keys, Home to reset)");
  splitter.tabIndex = 0;
  document.body.appendChild(splitter);

  function navBar() {
    return docs.shadowRoot && docs.shadowRoot.querySelector(".nav-bar");
  }

  function navMax() {
    return Math.max(NAV_MIN, Math.round(window.innerWidth * 0.6));
  }

  function clampNav(width) {
    return Math.min(navMax(), Math.max(NAV_MIN, Math.round(width)));
  }

  function setNavWidth(width) {
    docs.style.setProperty("--apiwarden-nav-width", width + "px");
    docs.setAttribute("data-nav-resized", "");
  }

  function placeSplitter() {
    var nav = navBar();
    var rect = nav && nav.getBoundingClientRect();
    // RapiDoc hides its nav on narrow screens; there is nothing to drag then.
    if (!rect || rect.width < 10 || getComputedStyle(nav).display === "none") {
      splitter.style.display = "none";
      return;
    }
    splitter.style.display = "";
    splitter.style.left = rect.right + "px";
    splitter.setAttribute("aria-valuenow", String(Math.round(rect.width)));
  }

  function saveNavWidth(width) {
    try {
      if (width) localStorage.setItem(NAV_KEY, String(width));
      else localStorage.removeItem(NAV_KEY);
    } catch (e) {
      // Resizing still works for this page load.
    }
  }

  function resetNavWidth() {
    docs.style.removeProperty("--apiwarden-nav-width");
    docs.removeAttribute("data-nav-resized");
    saveNavWidth(0);
    requestAnimationFrame(placeSplitter);
  }

  splitter.addEventListener("pointerdown", function (event) {
    var nav = navBar();
    if (!nav || event.button !== 0) return;
    event.preventDefault();
    var startX = event.clientX;
    var startWidth = nav.getBoundingClientRect().width;
    splitter.setPointerCapture(event.pointerId);
    splitter.classList.add("dragging");
    document.body.classList.add("nav-resizing");

    function move(e) {
      setNavWidth(clampNav(startWidth + (e.clientX - startX)));
      placeSplitter();
    }

    function stop() {
      splitter.removeEventListener("pointermove", move);
      splitter.removeEventListener("pointerup", stop);
      splitter.removeEventListener("pointercancel", stop);
      splitter.classList.remove("dragging");
      document.body.classList.remove("nav-resizing");
      var rect = nav.getBoundingClientRect();
      saveNavWidth(Math.round(rect.width));
    }

    splitter.addEventListener("pointermove", move);
    splitter.addEventListener("pointerup", stop);
    splitter.addEventListener("pointercancel", stop);
  });

  splitter.addEventListener("dblclick", resetNavWidth);

  splitter.addEventListener("keydown", function (event) {
    var nav = navBar();
    if (!nav) return;
    var step = event.shiftKey ? 40 : 10;
    var width = nav.getBoundingClientRect().width;
    if (event.key === "ArrowLeft") width -= step;
    else if (event.key === "ArrowRight") width += step;
    else if (event.key === "Home") return resetNavWidth();
    else return;
    event.preventDefault();
    width = clampNav(width);
    setNavWidth(width);
    saveNavWidth(width);
    placeSplitter();
  });

  var storedNav = 0;
  try {
    storedNav = parseInt(localStorage.getItem(NAV_KEY) || "0", 10) || 0;
  } catch (e) {
    storedNav = 0;
  }
  if (storedNav) setNavWidth(clampNav(storedNav));

  window.addEventListener("resize", function () {
    requestAnimationFrame(placeSplitter);
  });
  docs.addEventListener("spec-loaded", function () {
    // The nav is built after the spec; give it a frame to take its width.
    setTimeout(placeSplitter, 60);
  });

  /* ---------- extra servers for Try it (localhost, staging, …) ----------

     Held in localStorage, namespaced like the token. They are merged into the
     spec in front of its own servers before RapiDoc sees it, so they appear in
     its server dropdown and the newest one is selected by default. */

  var SERVERS_KEY = "apiwarden:servers:" + base;
  var serverForm = document.getElementById("server-form");
  var serverInput = document.getElementById("server-input");
  var serverList = document.getElementById("server-list");
  var serverError = document.getElementById("server-error");

  function readServers() {
    try {
      var list = JSON.parse(localStorage.getItem(SERVERS_KEY) || "[]");
      return Array.isArray(list) ? list.filter(function (u) { return typeof u === "string"; }) : [];
    } catch (e) {
      return [];
    }
  }

  function writeServers(list) {
    try {
      if (list.length) localStorage.setItem(SERVERS_KEY, JSON.stringify(list));
      else localStorage.removeItem(SERVERS_KEY);
    } catch (e) {
      // Works for this page load; just won't carry over.
    }
  }

  // "localhost:8000" -> "http://localhost:8000"; other bare hosts get https.
  // Returns "" for anything that isn't a usable http(s) base URL.
  function normalizeServer(raw) {
    var value = raw.trim();
    if (!value) return "";
    if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) {
      var local = /^(localhost|127\.\d+\.\d+\.\d+|\[::1\])(:|\/|$)/i.test(value);
      value = (local ? "http://" : "https://") + value;
    }
    try {
      var parsed = new URL(value);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
      if (!parsed.hostname) return "";
      return (parsed.origin + parsed.pathname).replace(/\/+$/, "");
    } catch (e) {
      return "";
    }
  }

  function renderServers() {
    if (!serverList) return;
    serverList.innerHTML = "";
    readServers().forEach(function (server) {
      var item = document.createElement("li");
      var label = document.createElement("span");
      label.textContent = server;
      label.title = server;
      var remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "\u00d7";
      remove.setAttribute("aria-label", "Remove server " + server);
      remove.addEventListener("click", function () {
        writeServers(readServers().filter(function (u) { return u !== server; }));
        renderServers();
        reloadSpec();
      });
      item.appendChild(label);
      item.appendChild(remove);
      serverList.appendChild(item);
    });
  }

  function showServerError(message) {
    if (!serverError) return;
    serverError.textContent = message;
    serverError.hidden = !message;
  }

  if (serverForm) {
    renderServers();
    serverForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var server = normalizeServer(serverInput.value);
      if (!server) {
        showServerError("Enter a http(s) address, like localhost:8000");
        return;
      }
      showServerError("");
      // Newest first, so it becomes the selected server.
      writeServers([server].concat(readServers().filter(function (u) { return u !== server; })));
      serverInput.value = "";
      renderServers();
      reloadSpec();
    });
    serverInput.addEventListener("input", function () { showServerError(""); });
  }

  function withServers(spec) {
    var extra = readServers();
    if (!extra.length || !spec || typeof spec !== "object") return spec;
    var own = (spec.servers || []).filter(function (s) { return extra.indexOf(s.url) === -1; });
    spec.servers = extra
      .map(function (u) { return { url: u, description: "Added in this browser" }; })
      .concat(own);
    return spec;
  }

  // The element has to be upgraded before it has loadSpec on it.
  var currentSource = config.spec;

  function loadIntoRenderer(source) {
    currentSource = source;
    var load = function () {
      if (!readServers().length) return docs.loadSpec(source);
      fetch(source, { credentials: "same-origin" })
        .then(function (response) {
          if (!response.ok) throw new Error(response.status);
          return response.json();
        })
        .then(function (spec) { docs.loadSpec(withServers(spec)); })
        .catch(function () { docs.loadSpec(source); }); // no extras beats no docs
    };
    if (typeof docs.loadSpec === "function") {
      load();
    } else if (window.customElements) {
      customElements.whenDefined("rapi-doc").then(load);
    }
  }

  function reloadSpec() {
    loadIntoRenderer(currentSource);
  }

  loadIntoRenderer(config.spec);

  /* ---------- "Copy link" and "Copy as curl" on every operation ----------

     RapiDoc has no slot for per-operation controls, so the buttons are added
     into its shadow root next to each operation's method-and-path line. It
     re-renders freely, so an observer puts them back whenever they go missing.
     The curl command is built by the server from the spec (see curl.py); the
     only part decided here is which server is selected, and — on Shift-click —
     the reader's own token, which never leaves the browser. */

  function operationFor(elementId) {
    var tags = (docs.resolvedSpec && docs.resolvedSpec.tags) || [];
    for (var i = 0; i < tags.length; i++) {
      var paths = tags[i].paths || [];
      for (var j = 0; j < paths.length; j++) {
        if (paths[j].elementId === elementId) return paths[j];
      }
    }
    return null;
  }

  function copyText(value) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(value);
    }
    // Plain http on a LAN address has no clipboard API; fall back to a selection.
    return new Promise(function (resolve, reject) {
      var area = document.createElement("textarea");
      area.value = value;
      area.style.cssText = "position:fixed;inset-block-start:0;opacity:0";
      document.body.appendChild(area);
      area.select();
      var ok = false;
      try {
        ok = document.execCommand("copy");
      } catch (e) {
        ok = false;
      }
      area.remove();
      ok ? resolve() : reject(new Error("copy blocked"));
    });
  }

  function shellEscapeInDoubleQuotes(value) {
    return value.replace(/[\\"$`]/g, "\\$&");
  }

  function buildCurl(operation, withToken) {
    var server = docs.selectedServer && (docs.selectedServer.computedUrl || docs.selectedServer.url);
    var id = operation.operationId || operation.method.toUpperCase() + " " + operation.path;
    var endpoint = url("curl/" + encodeURIComponent(id) + ".txt") + (server ? "?server=" + encodeURIComponent(server) : "");
    return fetch(endpoint, { credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) throw new Error(String(response.status));
        return response.text();
      })
      .then(function (command) {
        var token = withToken ? readToken() : "";
        return token ? command.split("$TOKEN").join(shellEscapeInDoubleQuotes(token)) : command;
      });
  }

  function flashButton(button, label) {
    if (!button.dataset.label) button.dataset.label = button.textContent;
    button.textContent = label;
    clearTimeout(button._reset);
    button._reset = setTimeout(function () {
      button.textContent = button.dataset.label;
    }, 1600);
  }

  function addOperationTools() {
    var root = docs.shadowRoot;
    if (!root) return;
    Array.prototype.forEach.call(root.querySelectorAll(".expanded-endpoint-body[id]"), function (body) {
      if (body.querySelector(":scope > .apiwarden-op-tools")) return;
      var bar = document.createElement("div");
      bar.className = "apiwarden-op-tools";
      bar.innerHTML =
        '<button type="button" class="apiwarden-op-btn" data-action="link" ' +
        'title="Copy a link straight to this operation">Copy link</button>' +
        '<button type="button" class="apiwarden-op-btn" data-action="curl" ' +
        'title="Copy a curl command for this operation, for the selected server. Shift-click to include your token.">' +
        "Copy as curl</button>";
      var line = body.querySelector(":scope > .mono-font");
      body.insertBefore(bar, line ? line.nextSibling : body.firstChild);
    });
  }

  function onOperationTool(event) {
    var button = event.target.closest && event.target.closest(".apiwarden-op-btn");
    if (!button) return;
    var body = button.closest(".expanded-endpoint-body");
    var operation = body && operationFor(body.id);
    if (!operation) return;

    var done = function () {
      flashButton(button, "Copied \u2713");
    };
    var failed = function () {
      flashButton(button, "Copy failed");
    };

    if (button.getAttribute("data-action") === "link") {
      var target =
        location.origin + url(config.app + "/") + "?op=" + encodeURIComponent(operation.method.toUpperCase() + " " + operation.path);
      copyText(target).then(done, failed);
    } else {
      buildCurl(operation, event.shiftKey).then(copyText).then(done, failed);
    }
  }

  customElements.whenDefined("rapi-doc").then(function () {
    var root = docs.shadowRoot;
    if (!root) return;
    root.addEventListener("click", onOperationTool);
    var scheduled = false;
    new MutationObserver(function () {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(function () {
        scheduled = false;
        addOperationTools();
      });
    }).observe(root, { childList: true, subtree: true });
    addOperationTools();
  });

  /* ---------- live updates, without losing the reader's place ---------- */

  if (config.watch && typeof EventSource !== "undefined") {
    var revision = config.revision;
    var events = new EventSource(url("events"));

    events.addEventListener("revision", function (event) {
      if (!revision || !event.data || event.data === revision) {
        revision = event.data;
        return;
      }
      revision = event.data;

      // Re-fetch and swap the spec in place. Bust the cache so a changed file
      // is never served from memory.
      loadIntoRenderer(config.spec + "?rev=" + encodeURIComponent(revision));
      flash("Documentation updated");
      setTimeout(loadNews, 400); // the changelog is written as the edit is noticed
    });
  }

  function flash(message) {
    var note = document.createElement("div");
    note.textContent = message;
    note.style.cssText =
      "position:fixed;inset-block-end:18px;inset-inline-end:18px;z-index:999;" +
      "padding:8px 14px;border-radius:6px;font:13px " +
      "-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;" +
      "background:#0066b8;color:#fff;box-shadow:0 4px 14px rgba(0,0,0,.25);" +
      "opacity:0;transition:opacity .2s";
    document.body.appendChild(note);
    requestAnimationFrame(function () {
      note.style.opacity = "1";
    });
    setTimeout(function () {
      note.style.opacity = "0";
      setTimeout(function () {
        note.remove();
      }, 300);
    }, 2200);
  }
})();
