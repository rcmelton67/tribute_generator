document.addEventListener("DOMContentLoaded", () => {
  // Archive search: show only matching tribute cards.
  const searchInput = document.getElementById("tributeSearch");
  const cards = Array.from(document.querySelectorAll(".mm-archive-card"));
  if (searchInput && cards.length) {
    const normalize = (value) => (value || "").toLowerCase().trim();
    const cardIndexText = new Map();

    cards.forEach((card) => {
      const datasetValues = Object.values(card.dataset || {}).join(" ");
      const visibleCardText = card.textContent || "";
      cardIndexText.set(card, normalize(`${datasetValues} ${visibleCardText}`));
    });

    searchInput.addEventListener("input", function () {
      const query = normalize(this.value);

      cards.forEach((card) => {
        const searchableText = cardIndexText.get(card) || "";
        const matches = !query || searchableText.includes(query);
        card.style.display = matches ? "" : "none";
      });
    });
  }
});
