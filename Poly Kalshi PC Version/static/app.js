(() => {
  /** Same as “Refresh data now”: POST /api/refresh → run_daily.py → reload. */
  const REFRESH_MS = 10 * 60 * 1000;
  const refreshButton = document.getElementById("refresh-data-btn");
  const refreshStatus = document.getElementById("refresh-status");
  let refreshInFlight = false;

  async function refreshData(options = { auto: false }) {
    if (!refreshButton || !refreshStatus) {
      return;
    }
    if (refreshInFlight) {
      return;
    }
    refreshInFlight = true;
    const auto = Boolean(options.auto);
    refreshButton.disabled = true;
    refreshStatus.textContent = auto ? "Auto-refreshing data..." : "Refreshing data...";
    try {
      const response = await fetch("/api/refresh", {
        method: "POST",
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        throw new Error(payload.message || "Refresh failed.");
      }
      refreshStatus.textContent = "Refresh complete. Reloading...";
      window.location.reload();
    } catch (error) {
      refreshStatus.textContent = `${auto ? "Auto-refresh" : "Refresh"} failed: ${error.message}`;
      refreshButton.disabled = false;
    } finally {
      refreshInFlight = false;
    }
  }

  if (refreshButton) {
    refreshButton.addEventListener("click", () => refreshData({ auto: false }));
  }

  const consensusTableWrap = document.getElementById("consensus-live-table");
  const consensusFilterBtn = document.getElementById("consensus-strict-filter-toggle");
  const consensusFilterLabel = consensusFilterBtn?.querySelector(".consensus-filter-toggle-label");
  if (consensusTableWrap && consensusFilterBtn && consensusFilterLabel) {
    const setFilterOn = (filterOn) => {
      consensusFilterBtn.setAttribute("aria-pressed", filterOn ? "true" : "false");
      consensusTableWrap.classList.toggle("show-relaxed-extras", !filterOn);
      consensusFilterLabel.textContent = filterOn
        ? "Consensus filter: ON (strict only)"
        : "Consensus filter: OFF (strict + relaxed-only picks)";
    };
    setFilterOn(true);
    consensusFilterBtn.addEventListener("click", () => {
      const filterOn = consensusFilterBtn.getAttribute("aria-pressed") === "true";
      setFilterOn(!filterOn);
    });
  }

  const allTradesBtn = document.getElementById("toggle-all-trades");
  if (allTradesBtn && consensusTableWrap) {
    allTradesBtn.addEventListener("click", () => {
      const on = consensusTableWrap.classList.toggle("show-all-trades");
      allTradesBtn.setAttribute("aria-expanded", on ? "true" : "false");
      allTradesBtn.textContent = on ? "Collapse all" : "Show all";
    });
  }

  window.setInterval(() => {
    refreshData({ auto: true });
  }, REFRESH_MS);
})();

