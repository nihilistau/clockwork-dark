// The admin panel's one script (spec §14.7). It ONLY refreshes read-only
// views: a section marked data-refresh="<url>" re-reads that JSON every few
// seconds and writes each value as TEXT (textContent, never HTML) into its
// data-field cells and data-list rows. Every page works without it: nothing
// depends on it, and it changes nothing on the server (GET only).
(function () {
  "use strict";
  var EVERY_MS = 5000;

  function setText(node, value) {
    node.textContent = value === null || value === undefined ? "" : String(value);
  }

  // A data-list's columns: its data-columns attribute (keys, space
  // separated; v0.20.0 T15), "slug state" when it names none.
  function fillList(body, rows) {
    var columns = (body.getAttribute("data-columns") || "slug state").split(/\s+/).filter(Boolean);
    while (body.firstChild) {
      body.removeChild(body.firstChild);
    }
    rows.forEach(function (row) {
      var tr = document.createElement("tr");
      columns.forEach(function (key) {
        var td = document.createElement("td");
        setText(td, row[key]);
        if (key === "state") {
          td.setAttribute("data-state", String(row.state || ""));
        }
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
  }

  function refresh(section) {
    var url = section.getAttribute("data-refresh");
    if (!url || url.indexOf("/admin/api/") !== 0) {
      return;
    }
    fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (data) {
        if (!data) {
          return;
        }
        section.querySelectorAll("[data-field]").forEach(function (node) {
          setText(node, data[node.getAttribute("data-field")]);
        });
        section.querySelectorAll("[data-list]").forEach(function (body) {
          var rows = data[body.getAttribute("data-list")];
          if (Array.isArray(rows)) {
            fillList(body, rows);
          }
        });
      })
      .catch(function () {
        /* the page as served stays; the next round tries again */
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var sections = document.querySelectorAll("[data-refresh]");
    sections.forEach(function (section) {
      window.setInterval(function () {
        refresh(section);
      }, EVERY_MS);
    });
  });
})();
