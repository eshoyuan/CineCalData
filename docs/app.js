const CANDIDATES_PER_DAY = 3;
const DATA_ROOT = ["localhost", "127.0.0.1"].includes(location.hostname)
  ? "../data"
  : "https://raw.githubusercontent.com/eshoyuan/CineCalData/main/data";
const state = { items: [], selectedDate: "", candidateIndex: 0 };
const $ = (id) => document.getElementById(id);

const localDateKey = (date = new Date()) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};
const parseDate = (value) => new Date(`${value}T12:00:00`);
const formatDay = (date) => String(parseDate(date).getDate());
const formatSubtitle = (date) => {
  const value = parseDate(date);
  return `${value.toLocaleDateString("en-US", { month: "short" })} ${value.toLocaleDateString("en-US", { weekday: "short" })}`.toUpperCase();
};
const formatFullDate = (date) => parseDate(date).toLocaleDateString("zh-CN", {
  year: "numeric", month: "long", day: "numeric", weekday: "long",
});
const hashDate = (value) => [...value].reduce((hash, character) => Math.imul(hash ^ character.charCodeAt(0), 16777619) >>> 0, 2166136261);
const quoteFor = (item) => {
  const source = (item?.editorial?.quote || item?.quote || "文艺短句正在等待编辑 Agent 完成。 ").trim();
  return source.length > 42 ? `${source.slice(0, 41)}…` : source;
};
const resolveImageURL = (url) => {
  if (!["localhost", "127.0.0.1"].includes(location.hostname) || !url) return url;
  const marker = "/main/data/";
  const offset = url.indexOf(marker);
  return offset >= 0 ? `../data/${url.slice(offset + marker.length)}` : url;
};

function candidatesFor(date) {
  if (!state.items.length) return [];
  const start = hashDate(date) % state.items.length;
  const stride = 137;
  return Array.from({ length: CANDIDATES_PER_DAY }, (_, index) => state.items[(start + index * stride) % state.items.length]);
}

function currentItem() {
  const candidates = candidatesFor(state.selectedDate);
  return candidates[state.candidateIndex % Math.max(candidates.length, 1)];
}

function previewEntry(item) {
  const douban = item?.ratings?.douban;
  return {
    title: item?.title || "当日尚未生成",
    ratingLabel: `豆瓣 ${douban.score.toFixed(1)}`,
    quote: quoteFor(item),
    imageURLSmall: resolveImageURL(item?.images?.small),
    imageURLMedium: resolveImageURL(item?.images?.medium),
    link: douban.url,
  };
}

function createWidget(item, date, size) {
  const entry = previewEntry(item);
  const widget = $("widgetTemplate").content.firstElementChild.cloneNode(true);
  widget.classList.add(size);
  widget.href = entry.link;
  const image = widget.querySelector(".widget-image");
  const url = size === "small" ? entry.imageURLSmall : entry.imageURLMedium;
  if (url) {
    image.src = url;
    image.alt = `${entry.title} ${size === "small" ? "小号" : "中号"}小组件背景图`;
    image.addEventListener("error", () => image.removeAttribute("src"));
  }
  widget.querySelector(".small-day").textContent = formatDay(date);
  widget.querySelector(".medium-day").textContent = formatDay(date);
  widget.querySelector(".medium-subtitle").textContent = formatSubtitle(date);
  widget.querySelectorAll(".movie-title").forEach((node) => { node.textContent = entry.title; });
  widget.querySelector(".book-title").textContent = `《${entry.title}》`;
  widget.querySelectorAll(".rating-badge").forEach((node) => { node.textContent = entry.ratingLabel; });
  widget.querySelectorAll(".movie-quote").forEach((node) => { node.textContent = entry.quote; });
  widget.setAttribute("aria-label", `${date}，${entry.title}，${entry.ratingLabel}`);
  return widget;
}

function render() {
  const item = currentItem();
  $("datePicker").value = state.selectedDate;
  $("smallWidget").replaceChildren(createWidget(item, state.selectedDate, "small"));
  $("mediumWidget").replaceChildren(createWidget(item, state.selectedDate, "medium"));
  $("selectedDateLabel").textContent = `${formatFullDate(state.selectedDate)} · ${item?.title || "暂无数据"}`;
  $("candidateLabel").textContent = `候选 ${state.candidateIndex + 1} / ${CANDIDATES_PER_DAY}`;
  const url = new URL(location.href);
  url.searchParams.set("date", state.selectedDate);
  url.searchParams.set("candidate", String(state.candidateIndex + 1));
  history.replaceState(null, "", url);
}

function moveDate(offset) {
  const date = parseDate(state.selectedDate);
  date.setDate(date.getDate() + offset);
  state.selectedDate = localDateKey(date);
  state.candidateIndex = 0;
  render();
}

async function loadData() {
  try {
    const response = await fetch(`${DATA_ROOT}/catalog.json`, { cache: "no-store" });
    if (!response.ok) throw new Error(`catalog ${response.status}`);
    const catalog = await response.json();
    state.items = (catalog.items || []).filter((item) => (
      item.images?.small
      && item.images?.medium
      && /^https:\/\/movie\.douban\.com\/subject\/\d+\/$/.test(item.ratings?.douban?.url || "")
      && Number.isFinite(item.ratings?.douban?.score)
      && item.ratings.douban.score >= 6
    ));
    const params = new URLSearchParams(location.search);
    state.selectedDate = /^\d{4}-\d{2}-\d{2}$/.test(params.get("date") || "") ? params.get("date") : localDateKey();
    state.candidateIndex = Math.min(CANDIDATES_PER_DAY - 1, Math.max(0, Number(params.get("candidate") || 1) - 1));
    render();
  } catch (error) {
    $("selectedDateLabel").textContent = `公开目录暂时无法读取 · ${error.message}`;
  }
}

$("previousDate").addEventListener("click", () => moveDate(-1));
$("nextDate").addEventListener("click", () => moveDate(1));
$("shuffleCandidate").addEventListener("click", () => {
  state.candidateIndex = (state.candidateIndex + 1) % CANDIDATES_PER_DAY;
  render();
});
$("shuffleDate").addEventListener("click", () => {
  const date = new Date();
  date.setDate(date.getDate() + Math.floor(Math.random() * 730) - 365);
  state.selectedDate = localDateKey(date);
  state.candidateIndex = 0;
  render();
});
$("datePicker").addEventListener("change", (event) => {
  state.selectedDate = event.target.value;
  state.candidateIndex = 0;
  render();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "ArrowLeft") moveDate(-1);
  if (event.key === "ArrowRight") moveDate(1);
});

loadData();
