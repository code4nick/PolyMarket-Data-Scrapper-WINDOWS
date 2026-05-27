(() => {
  /** Same as “Refresh data now”: POST /api/refresh → run_daily.py → reload. */
  const REFRESH_MS = 10 * 60 * 1000;
  const refreshButton = document.getElementById("refresh-data-btn");
  const refreshStatus = document.getElementById("refresh-status");
  let refreshInFlight = false;
  const saveBtn = document.getElementById("save-play-filters-btn");
  const saveStatus = document.getElementById("save-play-filters-status");

  async function refreshData(options = { auto: false }) {
    if (!refreshButton || !refreshStatus) {
      return false;
    }
    if (refreshInFlight) {
      return false;
    }
    refreshInFlight = true;
    const auto = Boolean(options.auto);
    const showLoading = Boolean(options.showLoading);
    const loadingOverlay = document.getElementById("loading-overlay");
    if (loadingOverlay && showLoading) loadingOverlay.classList.add("show");
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
      return true;
    } catch (error) {
      refreshStatus.textContent = `${auto ? "Auto-refresh" : "Refresh"} failed: ${error.message}`;
      refreshButton.disabled = false;
      if (loadingOverlay) loadingOverlay.classList.remove("show");
      return false;
    } finally {
      refreshInFlight = false;
    }
  }

  if (refreshButton) {
    refreshButton.addEventListener("click", () => refreshData({ auto: false }));
  }

  async function loadUiConfig() {
    try {
      const res = await fetch("/api/ui_config");
      const cfg = await res.json();
      if (!res.ok || !cfg) return;
      const minInput = document.getElementById("large-bet-min-usd");
      const maxInput = document.getElementById("large-bet-max-multiplier");
      const basisSelect = document.getElementById("large-bet-ratio-basis");
      if (minInput && typeof cfg.min_usd !== "undefined") minInput.value = cfg.min_usd;
      if (maxInput && typeof cfg.max_opposing_ratio !== "undefined") maxInput.value = cfg.max_opposing_ratio;
      if (basisSelect && cfg.ratio_basis) basisSelect.value = cfg.ratio_basis;
    } catch (_) {
      // Best effort; if config fetch fails, the page still renders with server-side defaults.
    }
  }

  async function saveUiConfig() {
    if (!saveBtn) return;
    const minInput = document.getElementById("large-bet-min-usd");
    const maxInput = document.getElementById("large-bet-max-multiplier");
    const basisSelect = document.getElementById("large-bet-ratio-basis");
    if (!minInput || !maxInput || !basisSelect) return;

    const minUsd = Number(minInput.value);
    const maxRatio = Number(maxInput.value);
    const ratioBasis = basisSelect.value;

    if (!Number.isFinite(minUsd) || !Number.isFinite(maxRatio)) {
      if (saveStatus) saveStatus.textContent = "Please enter valid numbers.";
      return;
    }

    saveBtn.disabled = true;
    if (saveStatus) saveStatus.textContent = "Saving...";
    try {
      const res = await fetch("/api/ui_config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          min_usd: minUsd,
          max_opposing_ratio: maxRatio,
          ratio_basis: ratioBasis,
        }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok || !payload.ok) {
        throw new Error(payload.message || "Save failed.");
      }
      if (saveStatus) saveStatus.textContent = "Saved. Next refresh will use these filters.";
    } catch (e) {
      if (saveStatus) saveStatus.textContent = e.message || "Save failed.";
    } finally {
      saveBtn.disabled = false;
    }
  }

  if (saveBtn) {
    saveBtn.addEventListener("click", saveUiConfig);
  }

  loadUiConfig();

  // Cold-start: UI renders immediately with empty data; show overlay while refresh runs.
  const coldStartKey = "polyKalshiColdStartDone";
  if (window.COLD_START && !sessionStorage.getItem(coldStartKey)) {
    sessionStorage.setItem(coldStartKey, "1");
    (async () => {
      for (let attempt = 1; attempt <= 5; attempt++) {
        const ok = await refreshData({ auto: false, showLoading: true });
        if (ok) return;
        // If the server isn't ready yet, retry a couple seconds later.
        await new Promise((r) => setTimeout(r, 2000));
      }
    })();
  }

  window.setInterval(() => {
    refreshData({ auto: true });
  }, REFRESH_MS);
})();
