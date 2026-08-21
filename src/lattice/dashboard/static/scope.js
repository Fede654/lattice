/* Project scope bar.
 *
 * Turns the single-project dashboard into a multi-project one without
 * touching any feature code: every API call already funnels through api()
 * in index.html, which appends window.LatticeScope.param() to the path.
 * Selecting a project therefore re-points the *entire* dashboard — board,
 * graph, structure, activity, task detail, writes — at that project's
 * .lattice directory, with all features intact.
 *
 * When the server was started without --scope, /api/scope reports
 * enabled:false and this file renders nothing at all.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "lattice.scope.project";
  var ALL = "__all__";
  // Read synchronously at load: this file is loaded *before* the dashboard's
  // own script, whose init() fires /api/config, /api/tasks and /api/graph the
  // moment it runs. Waiting for /api/scope to answer would let those first
  // requests go out unscoped and paint another project's board.
  //
  // With nothing stored, the aggregate opens on every project at once: the
  // command was asked for to see across repositories, so a single project is
  // the narrowing choice, not the starting point.
  var current = ALL;
  try {
    current = localStorage.getItem(STORAGE_KEY) || ALL;
  } catch (e) {
    current = ALL;
  }
  var projects = [];

  window.LatticeScope = {
    /** Query fragment to append to an API path ("" when not scoped). */
    param: function () {
      return current ? "project=" + encodeURIComponent(current) : "";
    },
    current: function () {
      return current;
    },
    isAll: function () {
      return current === ALL;
    },

    /* id -> [project, ...] for the rows currently on the board. Built from
     * the merged /api/tasks response so an action can find its own board. */
    _owners: {},

    indexTasks: function (rows) {
      if (!Array.isArray(rows)) return;
      var map = {};
      rows.forEach(function (r) {
        if (!r || !r.id || !r.project) return;
        (map[r.id] = map[r.id] || []).push(r.project);
      });
      this._owners = map;
      reportDuplicates(rows);
    },

    /* Query fragment for a request path.
     *
     * Only a request against a *specific* task needs special handling in ALL
     * mode: it is routed to the board that task was read from. Everything
     * else — the task list, config, stats — carries the ALL marker so the
     * server merges the boards. Returning "" here instead would drop the
     * marker and silently serve the default project alone.
     *
     * When the same id lives in more than one board — copied .lattice
     * directories do this — there is no safe answer, so the action is refused
     * rather than guessing. That is the duplication showing itself, which is
     * the point of not hiding it. */
    paramForPath: function (path) {
      if (current !== ALL) return this.param();
      var m = /^\/api\/tasks\/(task_[A-Za-z0-9]+)/.exec(path);
      if (!m) return this.param();
      var owners = this._owners[m[1]] || [];
      if (owners.length === 1) return "project=" + encodeURIComponent(owners[0]);
      if (owners.length > 1) {
        throw new Error(
          "This task exists in " + owners.length + " boards (" + owners.join(", ") +
          "). Switch to one project to act on it."
        );
      }
      // Owner unknown: keep the ALL marker so the request fails as a clean
      // miss rather than resolving against whichever board happens to be
      // default, which could hold a different task under the same id.
      return this.param();
    },
    /* Query fragment for an action on a known card object. */
    paramForTask: function (task) {
      if (current === ALL) {
        if (task && task.project) return "project=" + encodeURIComponent(task.project);
        return "";
      }
      return this.param();
    }
  };

  /* Duplicated tasks are a data problem, not a display problem: copied
   * .lattice directories scatter the same work across boards. ALL mode shows
   * every row and says how many are duplicated, so the copies can be found
   * and reconciled rather than quietly averaged away. */
  function reportDuplicates(rows) {
    var dupRows = rows.filter(function (r) { return r.duplicate_in && r.duplicate_in.length; });
    var slot = document.querySelector(".scope-dupes");
    if (!slot) return;
    if (!dupRows.length) {
      slot.textContent = "";
      slot.removeAttribute("title");
      return;
    }
    var pairs = {};
    dupRows.forEach(function (r) {
      var key = [r.project].concat(r.duplicate_in).sort().join(" == ");
      pairs[key] = (pairs[key] || 0) + 1;
    });
    slot.textContent = dupRows.length + " duplicated rows";
    slot.title =
      "The same task appears in more than one board:\n" +
      Object.keys(pairs).map(function (k) { return "  " + k + "  (" + pairs[k] + ")"; }).join("\n") +
      "\n\nThese are copied .lattice directories. Reconcile them at the source.";
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function select(name) {
    current = name;
    if (name) {
      localStorage.setItem(STORAGE_KEY, name);
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
    // A full reload is the honest way to re-point every view at once: the
    // dashboard caches task data in many places, and re-fetching piecemeal
    // would leave stale panels from the previous project on screen.
    location.reload();
  }

  function render(data) {
    var bar = el("div", "scope-bar");

    var label = el("span", "scope-label", "Project");
    bar.appendChild(label);

    var picker = el("select", "scope-select");
    var seen = false;

    var allOpt = el("option", null, "All projects");
    allOpt.value = ALL;
    if (current === ALL) { allOpt.selected = true; seen = true; }
    picker.appendChild(allOpt);

    projects.forEach(function (p) {
      var opt = el("option", null, p.name + (p.project_code ? "  [" + p.project_code + "]" : ""));
      opt.value = p.name;
      if (!p.ok) {
        opt.textContent = p.name + "  (unreadable)";
        opt.disabled = true;
      }
      if (p.name === current) {
        opt.selected = true;
        seen = true;
      }
      picker.appendChild(opt);
    });

    // A stored selection can point at a project that has since disappeared.
    if (current && !seen) {
      select(null);
      return;
    }

    picker.addEventListener("change", function () {
      select(picker.value);
    });
    bar.appendChild(picker);

    if (current === ALL) {
      var totals = projects.reduce(function (acc, p) {
        if (p.ok) { acc.open += p.open_count; acc.all += p.task_count; acc.n += 1; }
        return acc;
      }, { open: 0, all: 0, n: 0 });
      bar.appendChild(el("span", "scope-meta",
        totals.open + " open / " + totals.all + " tasks across " + totals.n + " projects"));
      bar.appendChild(el("span", "scope-warn-soft", "create a task inside a project"));
      bar.appendChild(el("span", "scope-dupes", ""));
      var brokenAll = projects.filter(function (p) { return !p.ok; }).length;
      if (brokenAll) bar.appendChild(el("span", "scope-warn", brokenAll + " unreadable"));
      document.body.insertBefore(bar, document.body.firstChild);
      document.body.classList.add("has-scope-bar");
      return;
    }

    var active = projects.filter(function (p) {
      return p.name === current;
    })[0];
    var shown = active || projects.filter(function (p) { return p.name === data.default; })[0];
    if (shown) {
      bar.appendChild(el("span", "scope-meta",
        shown.open_count + " open / " + shown.task_count + " tasks"));
      bar.appendChild(el("span", "scope-path", shown.root));
    }

    var broken = projects.filter(function (p) { return !p.ok; }).length;
    if (broken) {
      bar.appendChild(el("span", "scope-warn", broken + " unreadable"));
    }

    document.body.insertBefore(bar, document.body.firstChild);
    document.body.classList.add("has-scope-bar");
  }

  function boot() {
    fetch("/api/scope")
      .then(function (r) { return r.json(); })
      .then(function (body) {
        if (!body.ok || !body.data || !body.data.enabled) return;
        projects = body.data.projects || [];
        if (!projects.length) return;
        if (!current) current = body.data.default || null;
        render(body.data);
      })
      .catch(function () { /* scope is optional; never break the dashboard */ });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
