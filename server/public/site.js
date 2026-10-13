// Przebieg naprawy na stronie głównej: lista kroków działa jak karty, obok zrzut wybranego kroku.
// Bez JS (html bez klasy .js) wszystkie zrzuty są widoczne pod sobą.
const tabs = [...document.querySelectorAll(".step-list [role=tab]")];

function select(tab, focus) {
  for (const t of tabs) {
    const on = t === tab;
    t.setAttribute("aria-selected", String(on));
    t.tabIndex = on ? 0 : -1;
    document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
  }
  if (focus) tab.focus();
}

tabs.forEach((tab, i) => {
  tab.addEventListener("click", () => select(tab, false));
  tab.addEventListener("keydown", (e) => {
    const step = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[e.key];
    if (e.key === "Home") select(tabs[0], true);
    else if (e.key === "End") select(tabs[tabs.length - 1], true);
    else if (step) select(tabs[(i + step + tabs.length) % tabs.length], true);
    else return;
    e.preventDefault();
  });
});

if (tabs.length) select(tabs[0], false);
