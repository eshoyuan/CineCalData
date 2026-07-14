const state = { entries: [], selectedDate: "" };
const $ = (id) => document.getElementById(id);
const DATA_ROOT = "https://raw.githubusercontent.com/eshoyuan/CineCalData/main/data";

const formatDay = (date) => String(new Date(`${date}T12:00:00`).getDate());
const formatSubtitle = (date) => {
  const value = new Date(`${date}T12:00:00`);
  return `${value.toLocaleDateString("en-US", { month: "short" })} ${value.toLocaleDateString("en-US", { weekday: "short" })}`.toUpperCase();
};
const formatFullDate = (date) => new Date(`${date}T12:00:00`).toLocaleDateString("zh-CN", {
  year: "numeric",
  month: "long",
  day: "numeric",
  weekday: "long",
});

function createWidget(entry, date, size) {
  const widget = $("widgetTemplate").content.firstElementChild.cloneNode(true);
  widget.classList.add(size);
  widget.href = entry?.doubanURL || "#";
  if (!entry?.doubanURL) widget.removeAttribute("href");
  const image = widget.querySelector(".widget-image");
  const url = size === "small" ? entry?.imageURLSmall || entry?.imageURL : entry?.imageURLMedium || entry?.imageURL;
  if (url) {
    image.src = url;
    image.alt = `${entry.title} 小组件背景图`;
    image.addEventListener("error", () => image.removeAttribute("src"));
  }
  widget.querySelector(".small-day").textContent = formatDay(date);
  widget.querySelector(".medium-day").textContent = formatDay(date);
  widget.querySelector(".medium-subtitle").textContent = formatSubtitle(date);
  widget.querySelectorAll(".movie-title").forEach((node) => node.textContent = entry?.title || "当日尚未生成");
  widget.querySelector(".book-title").textContent = `《${entry?.title || "当日尚未生成"}》`;
  widget.querySelectorAll(".rating-badge").forEach((node) => node.textContent = `豆瓣 ${entry?.rating || "—"}`);
  widget.querySelectorAll(".movie-quote").forEach((node) => node.textContent = entry?.quote || "这一帧还在路上。换一个日期看看吧。" );
  widget.setAttribute("aria-label", `${date}，${entry?.title || "暂无数据"}`);
  return widget;
}

function currentEntry() { return state.entries.find((entry) => entry.date === state.selectedDate); }
function render() {
  const entry = currentEntry();
  $("datePicker").value = state.selectedDate;
  $("smallWidget").replaceChildren(createWidget(entry, state.selectedDate, "small"));
  $("mediumWidget").replaceChildren(createWidget(entry, state.selectedDate, "medium"));
  $("selectedDateLabel").textContent = entry ? `${formatFullDate(state.selectedDate)} · ${entry.title}` : `${formatFullDate(state.selectedDate)} · 尚未生成`;
  const url = new URL(location.href);
  url.searchParams.set("date", state.selectedDate);
  url.searchParams.delete("size");
  history.replaceState(null, "", url);
}

function moveDate(offset) {
  const dates = state.entries.map((entry) => entry.date).sort();
  let index = dates.indexOf(state.selectedDate);
  if (index < 0) index = 0;
  state.selectedDate = dates[(index + offset + dates.length) % dates.length];
  render();
}

async function loadData() {
  try {
    const calendarResponse = await fetch(`${DATA_ROOT}/calendar.json`, { cache: "no-store" });
    if (!calendarResponse.ok) throw new Error(`calendar ${calendarResponse.status}`);
    const calendar = await calendarResponse.json();
    state.entries = (calendar.entries || []).sort((a, b) => a.date.localeCompare(b.date));
    const requested = new URLSearchParams(location.search).get("date");
    const today = new Date().toLocaleDateString("en-CA");
    state.selectedDate = state.entries.some((entry) => entry.date === requested) ? requested : state.entries.some((entry) => entry.date === today) ? today : state.entries.at(-1)?.date;
    const dates = state.entries.map((entry) => entry.date);
    $("datePicker").min = dates[0] || ""; $("datePicker").max = dates.at(-1) || "";
    render();
  } catch (error) {
    $("selectedDateLabel").textContent = `公开数据暂时无法读取 · ${error.message}`;
  }
}

$("previousDate").addEventListener("click", () => moveDate(-1));
$("nextDate").addEventListener("click", () => moveDate(1));
$("shuffleDate").addEventListener("click", () => {
  if (!state.entries.length) return;
  const alternatives = state.entries.filter((entry) => entry.date !== state.selectedDate);
  state.selectedDate = (alternatives[Math.floor(Math.random() * alternatives.length)] || state.entries[0]).date;
  render();
});
$("datePicker").addEventListener("change", (event) => { state.selectedDate = event.target.value; render(); });
document.addEventListener("keydown", (event) => { if (event.key === "ArrowLeft") moveDate(-1); if (event.key === "ArrowRight") moveDate(1); });

loadData();
