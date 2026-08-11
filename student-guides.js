(() => {
  "use strict";
  const phaseDetails = [...document.querySelectorAll("details.phase-card")];
  const openHash = () => {
    const id = decodeURIComponent(location.hash.slice(1));
    if (!id) return;
    const target = document.getElementById(id);
    if (target instanceof HTMLDetailsElement && target.classList.contains("phase-card")) target.open = true;
  };
  phaseDetails.forEach((detail) => detail.addEventListener("toggle", () => {
    if (detail.open) history.replaceState(null, "", `#${encodeURIComponent(detail.id)}`);
  }));
  addEventListener("hashchange", openHash);
  openHash();
  let printState = [];
  addEventListener("beforeprint", () => {
    printState = phaseDetails.map((detail) => detail.open);
    phaseDetails.forEach((detail) => { detail.open = true; });
  });
  addEventListener("afterprint", () => phaseDetails.forEach((detail, index) => { detail.open = printState[index] ?? detail.open; }));
})();
