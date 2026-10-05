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
