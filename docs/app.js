const state = { entries: [], plans: [], selectedDate: "", phoneSize: "medium" };
const $ = (id) => document.getElementById(id);

const formatDay = (date) => String(new Date(`${date}T12:00:00`).getDate());
const formatSubtitle = (date) => {
  const value = new Date(`${date}T12:00:00`);
  return `${value.toLocaleDateString("en-US", { month: "short" })} ${value.toLocaleDateString("en-US", { weekday: "short" })}`.toUpperCase();
};
const isComplete = (entry) => Boolean(entry?.imageURLSmall && entry?.imageURLMedium);

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
function currentPlan() { return state.plans.find((entry) => entry.date === state.selectedDate); }

function render() {
  const entry = currentEntry();
  const plan = currentPlan();
  $("datePicker").value = state.selectedDate;
  const phone = $("phoneWidget");
  phone.replaceChildren(createWidget(entry, state.selectedDate, state.phoneSize));
  phone.classList.toggle("small-slot", state.phoneSize === "small");
  $("smallWidget").replaceChildren(createWidget(entry, state.selectedDate, "small"));
  $("mediumWidget").replaceChildren(createWidget(entry, state.selectedDate, "medium"));
  document.querySelectorAll("[data-size]").forEach((button) => button.classList.toggle("active", button.dataset.size === state.phoneSize));

  const complete = isComplete(entry);
  $("statusDot").className = complete ? "ready" : entry ? "missing" : "missing";
  $("dataStatus").textContent = complete ? "完整卡片已缓存" : entry ? "已有文字，图片待生成" : "该日期尚无数据";
  $("selectionReason").textContent = plan?.reason || (entry ? "这是一条已有的日历卡片；长期选片依据尚未写入计划。" : "选择另一个日期，或点击“随机一天”浏览已有卡片。");
  $("metaTitle").textContent = entry?.title || "—";
  $("metaRating").textContent = entry?.rating ? `${entry.rating} / 10` : "—";
  $("metaSource").textContent = entry?.imageSourcePageURL ? new URL(entry.imageSourcePageURL).hostname.replace("www.", "") : "—";
  $("metaUpdated").textContent = entry?.ratingRetrievedAt ? new Date(entry.ratingRetrievedAt).toLocaleString("zh-CN", { dateStyle: "medium", timeStyle: "short" }) : "—";
  const link = $("doubanLink");
  link.href = entry?.doubanURL || "#";
  link.classList.toggle("disabled", !entry?.doubanURL);
  const url = new URL(location.href); url.searchParams.set("date", state.selectedDate); url.searchParams.set("size", state.phoneSize); history.replaceState(null, "", url);
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
    const [calendarResponse, planResponse] = await Promise.all([fetch("data/calendar.json", { cache: "no-store" }), fetch("data/plan.json", { cache: "no-store" })]);
    if (!calendarResponse.ok) throw new Error(`calendar ${calendarResponse.status}`);
    const calendar = await calendarResponse.json();
    const plan = planResponse.ok ? await planResponse.json() : { entries: [] };
    state.entries = (calendar.entries || []).sort((a, b) => a.date.localeCompare(b.date));
    state.plans = plan.entries || [];
    const requested = new URLSearchParams(location.search).get("date");
    const requestedSize = new URLSearchParams(location.search).get("size");
    const today = new Date().toLocaleDateString("en-CA");
    state.selectedDate = state.entries.some((entry) => entry.date === requested) ? requested : state.entries.some((entry) => entry.date === today) ? today : state.entries.at(-1)?.date;
    state.phoneSize = requestedSize === "small" ? "small" : "medium";
    const dates = state.entries.map((entry) => entry.date);
    $("datePicker").min = dates[0] || ""; $("datePicker").max = dates.at(-1) || "";
    render();
  } catch (error) {
    $("dataStatus").textContent = "公开数据暂时无法读取";
    $("statusDot").className = "missing";
    $("selectionReason").textContent = `请稍后刷新。${error.message}`;
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
document.querySelectorAll("[data-size]").forEach((button) => button.addEventListener("click", () => { state.phoneSize = button.dataset.size; render(); }));
document.addEventListener("keydown", (event) => { if (event.key === "ArrowLeft") moveDate(-1); if (event.key === "ArrowRight") moveDate(1); });

const updateClock = () => $("statusTime").textContent = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
updateClock(); setInterval(updateClock, 30_000); loadData();
