document.addEventListener("DOMContentLoaded", () => {
  // Archive search: show only matching tribute cards.
  const searchInput = document.getElementById("tributeSearch");
  const cards = Array.from(document.querySelectorAll(".mm-archive-card"));
  if (searchInput && cards.length) {
    const normalize = (value) => (value || "").toLowerCase().trim();

    searchInput.addEventListener("input", function () {
      const query = normalize(this.value);

      cards.forEach((card) => {
        const searchableText = normalize(
          `${card.dataset.name || ""} ${card.dataset.breed || ""} ${card.dataset.years || ""} ${card.dataset.content || ""}`
        );

        const words = searchableText.split(/\s+/).filter(Boolean);
        const startsWithWord = words.some((word) => word.startsWith(query));
        const includesAnywhere = searchableText.includes(query);
        const matches = !query || startsWithWord || includesAnywhere;
        card.style.display = matches ? "" : "none";
      });
    });
  }

  // If we're on a single tribute page, stop here.
  if (document.querySelector(".mm-tribute-system")) return;

  // Archive/card pages: shrink long placeholder names
  const names = document.querySelectorAll(".mm-image-wrapper.mm-placeholder .mm-stone-name");
  if (!names.length) return;

  names.forEach((el) => {
    const name = (el.textContent || "").trim();
    const len = name.length;

    // Base: make cards consistent
    el.style.width = "50%";
    el.style.maxWidth = "200px";

    let fontSize = 26;
    if (len <= 4) fontSize = 30;
    else if (len <= 8) fontSize = 28;
    else if (len <= 14) fontSize = 24;
    else if (len <= 20) fontSize = 20;
    else fontSize = 18;

    el.style.fontSize = `${fontSize}px`;
  });
});
