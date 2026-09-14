"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  Bell,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  Clock,
  Home,
  ListTodo,
  Menu,
  MessageCircle,
  Send,
  Trophy,
  User,
  Users,
} from "lucide-react";

const nav = [
  { id: "home", label: "ホーム", icon: Home },
  { id: "tasks", label: "To Do", icon: ListTodo },
  { id: "calendar", label: "カレンダー", icon: CalendarDays },
  { id: "attendance", label: "出欠申請", icon: ClipboardCheck },
  { id: "notices", label: "お知らせ", icon: Bell },
  { id: "contact", label: "連絡", icon: MessageCircle },
  { id: "members", label: "部員一覧", icon: Users },
  { id: "ranking", label: "ランキング", icon: Trophy },
  { id: "profile", label: "マイページ", icon: User },
  { id: "approvals", label: "承認待ち", icon: Check, approvalOnly: true },
  { id: "ops", label: "運営", icon: Users, managerOnly: true },
];

const mobileNav = ["home", "calendar", "attendance", "notices", "approvals", "ops", "members", "profile"];
const managerRoles = new Set(["パートリーダー", "部長", "副部長", "管理者"]);
const approvalRoles = new Set(["パートリーダー", "部長", "副部長", "管理者"]);
const isLocalFrontend =
  typeof window !== "undefined"
  && ["localhost", "127.0.0.1"].includes(window.location.hostname);
const isPortfolioDemo =
  typeof window !== "undefined"
  && window.location.hostname === "bandattend-portfolio-demo.vercel.app";
const configuredApiBase = process.env.NEXT_PUBLIC_API_BASE;
const API_BASE = isPortfolioDemo
  ? ""
  : (isLocalFrontend ? (configuredApiBase || "http://localhost:8000") : "");

async function fetchApi(url, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  try {
    return await window.fetch(url, options);
  } catch (error) {
    if (!(error instanceof TypeError) || method !== "GET") throw error;
    await new Promise((resolve) => window.setTimeout(resolve, 800));
    try {
      return await window.fetch(url, options);
    } catch (retryError) {
      if (retryError instanceof TypeError) {
        throw new Error("接続に失敗しました。通信状態を確認して、もう一度お試しください");
      }
      throw retryError;
    }
  }
}
const eventTypes = ["通常練習", "合奏", "分奏", "パート練習", "本番", "コンクール", "定期演奏会", "依頼演奏", "その他"];
const partOptions = ["フルート", "クラリネット", "サックス", "トランペット", "ホルン", "トロンボーン", "ユーフォニアム", "バスパート", "パーカッション"];
const weekdayOptions = ["月", "火", "水", "木", "金", "土", "日"];
const DATA_CACHE_TTL = 60000;
const dataCache = new Map();
const pendingDataRequests = new Map();
const API_WAKEUP_NOTICE_DELAY = 2500;
const SAVED_LOGIN_KEY = "bandattend_saved_login";
const portfolioDemoRoles = [
  { label: "一般部員", description: "予定確認・出欠申請・お知らせ", studentId: "portfolio-demo", pin: "2580" },
  { label: "パートリーダー", description: "自分のパートの承認・出席確認", studentId: "2", pin: "2" },
  { label: "部長", description: "全部員の承認・運営情報", studentId: "0", pin: "0" },
  { label: "副部長", description: "部長と連携する運営画面", studentId: "1", pin: "1" },
  { label: "先生", description: "先生向け予定・お知らせ画面", studentId: "3", pin: "3" },
  { label: "管理者", description: "管理・分析機能の閲覧", studentId: "portfolio-ops", pin: "2580" },
];
const NEXT_PERFORMANCE_CACHE_KEY = "bandattend_next_performance";
const japaneseWeekdays = ["日", "月", "火", "水", "木", "金", "土"];

function weekdayForDate(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return "";
  const [, year, month, day] = match;
  return japaneseWeekdays[new Date(Number(year), Number(month) - 1, Number(day)).getDay()];
}

function formatDateWithWeekday(value) {
  if (!value) return value;
  const text = String(value);
  const match = text.match(/^(\d{4}-\d{2}-\d{2})(.*)$/);
  if (!match) return text;
  const weekday = weekdayForDate(match[1]);
  return weekday ? `${match[1]}（${weekday}）${match[2]}` : text;
}

function formatLoginDateTime(value) {
  if (!value) return "記録なし";
  const text = String(value);
  const normalized = text.includes("T") ? text : `${text.replace(" ", "T")}Z`;
  const parsed = new Date(normalized);
  if (Number.isNaN(parsed.getTime())) return text;
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function weekRangeForDate(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return { startDate: value, endDate: value };
  const selected = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  const monday = new Date(selected);
  monday.setDate(selected.getDate() - ((selected.getDay() + 6) % 7));
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  const key = (item) => `${item.getFullYear()}-${String(item.getMonth() + 1).padStart(2, "0")}-${String(item.getDate()).padStart(2, "0")}`;
  return { startDate: key(monday), endDate: key(sunday) };
}

function monthRangeForDate(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return { startDate: value, endDate: value };
  const year = Number(match[1]);
  const month = Number(match[2]);
  const endDay = new Date(year, month, 0).getDate();
  return {
    startDate: `${match[1]}-${match[2]}-01`,
    endDate: `${match[1]}-${match[2]}-${String(endDay).padStart(2, "0")}`,
  };
}

function suggestedExternalSystemIcon(value) {
  try {
    const parsed = new URL(value);
    if (parsed.hostname === "playful-centaur-45662c.netlify.app") {
      return "https://playful-centaur-45662c.netlify.app/icon-180.png";
    }
  } catch {
    return "";
  }
  return "";
}

function todayKey() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function normalizeNextPerformance(nextPerformance) {
  if (!nextPerformance?.date) return null;
  const today = new Date(`${todayKey()}T00:00:00`);
  const performanceDate = new Date(`${nextPerformance.date}T00:00:00`);
  const daysLeft = Math.round((performanceDate - today) / 86400000);
  if (daysLeft < 0) return null;
  return {
    ...nextPerformance,
    daysLeft,
    label: daysLeft === 0 ? "本日" : `あと${daysLeft}日`,
  };
}

function loadSavedNextPerformance() {
  if (typeof window === "undefined") return null;
  try {
    const saved = JSON.parse(window.localStorage.getItem(NEXT_PERFORMANCE_CACHE_KEY) || "null");
    if (!saved?.showNextPerformance) return null;
    return normalizeNextPerformance(saved.nextPerformance);
  } catch {
    window.localStorage.removeItem(NEXT_PERFORMANCE_CACHE_KEY);
    return null;
  }
}

function saveNextPerformance(payload) {
  if (typeof window === "undefined") return;
  if (!payload?.showNextPerformance || !payload.nextPerformance) {
    window.localStorage.removeItem(NEXT_PERFORMANCE_CACHE_KEY);
    return;
  }
  window.localStorage.setItem(NEXT_PERFORMANCE_CACHE_KEY, JSON.stringify({
    showNextPerformance: true,
    nextPerformance: payload.nextPerformance,
  }));
}

function cacheKey(token, path) {
  return `${token || "guest"}:${path}`;
}

function getCachedData(token, path) {
  const cached = dataCache.get(cacheKey(token, path));
  if (!cached) return null;
  if (Date.now() - cached.time > DATA_CACHE_TTL) return null;
  return cached.data;
}

function setCachedData(token, path, data) {
  dataCache.set(cacheKey(token, path), { data, time: Date.now() });
}

async function fetchJsonCached(token, path, options = {}) {
  const key = cacheKey(token, path);
  if (!options.force) {
    const cached = getCachedData(token, path);
    if (cached) return cached;
    const pending = pendingDataRequests.get(key);
    if (pending) return pending;
  }
  const request = (async () => {
    const response = await fetchApi(`${API_BASE}${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) throw new Error(options.errorMessage || "読み込めませんでした");
    const data = await response.json();
    setCachedData(token, path, data);
    return data;
  })();
  pendingDataRequests.set(key, request);
  try {
    return await request;
  } finally {
    if (pendingDataRequests.get(key) === request) pendingDataRequests.delete(key);
  }
}

function invalidateCache(token, startsWith = "") {
  const prefix = `${token || "guest"}:${startsWith}`;
  Array.from(dataCache.keys()).forEach((key) => {
    if (key.startsWith(prefix)) dataCache.delete(key);
  });
}

function prefetchJson(token, path) {
  if (!token || getCachedData(token, path)) return;
  fetchJsonCached(token, path).catch(() => {});
}

function prefetchCommonScreens(token, user) {
  if (!token) return;
  const run = () => {
    const now = new Date();
    const month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
    prefetchJson(token, `/api/events?month=${month}`);
    if (user?.permissions?.canSubmitAttendance) prefetchJson(token, "/api/attendance/targets");
    prefetchJson(token, "/api/announcements?filter=unread");
    prefetchJson(token, "/api/todos");
    prefetchJson(token, "/api/part-memos");
    prefetchJson(token, `/api/rankings?month=${month}`);
    prefetchJson(token, "/api/members");
    if (approvalRoles.has(user?.role)) prefetchJson(token, "/api/approvals");
  };
  if (typeof window !== "undefined" && "requestIdleCallback" in window) {
    window.requestIdleCallback(run, { timeout: 2000 });
  } else if (typeof window !== "undefined") {
    window.setTimeout(run, 700);
  }
}

function navForUser(user) {
  return nav.filter((item) =>
    (!item.managerOnly || user?.permissions?.canViewOperations || managerRoles.has(user?.role))
    && (!item.approvalOnly || approvalRoles.has(user?.role))
    && (item.id !== "attendance" || user?.permissions?.canSubmitAttendance)
  );
}

const fallbackHomeData = {
  today: new Date().toISOString().slice(0, 10),
  showNextPerformance: false,
  nextPerformance: null,
  todayEvents: [],
  unreadNotifications: [],
  birthdays: [],
  birthdayDate: null,
  birthdaysAreToday: false,
  leaveCredits: { enabled: false, available: 0 },
  externalSystemLinks: [],
  attendanceStats: null,
  taskDate: null,
  taskHasEvents: false,
  tasks: [],
};

function TopBar({ title, user, canGoBack, onBack }) {
  return (
    <header className="topbar">
      {canGoBack ? (
        <button className="icon-button" aria-label="前のページに戻る" onClick={onBack}>
          <ArrowLeft size={24} />
        </button>
      ) : (
        <div className="topbar-spacer" aria-hidden="true" />
      )}
      <h1>{title}</h1>
      <div className="avatar">{user?.name?.slice(0, 1) || "B"}</div>
    </header>
  );
}

function Sidebar({ active, setActive, visibleNav }) {
  const main = visibleNav.filter((item) => ["home", "tasks", "calendar", "attendance", "notices", "contact"].includes(item.id));
  const self = visibleNav.filter((item) => ["members", "ranking", "profile"].includes(item.id));
  const ops = visibleNav.filter((item) => ["approvals", "ops"].includes(item.id));
  return (
    <aside className="sidebar">
      <div className="brand">BandAttend</div>
      <SideGroup label="メイン" items={main} active={active} setActive={setActive} />
      <SideGroup label="自分" items={self} active={active} setActive={setActive} />
      {ops.length > 0 && <SideGroup label="運営" items={ops} active={active} setActive={setActive} />}
    </aside>
  );
}

function SideGroup({ label, items, active, setActive }) {
  return (
    <>
      <div className="side-label">{label}</div>
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <button
            className={`side-link ${active === item.id ? "active" : ""}`}
            key={item.id}
            onClick={() => setActive(item.id)}
          >
            <Icon size={18} />
            {item.label}
          </button>
        );
      })}
    </>
  );
}

function BottomNav({ active, setActive, visibleNav, unreadNotices = 0, currentUser }) {
  const [moreOpen, setMoreOpen] = useState(false);
  const allItems = mobileNav
    .map((id) => visibleNav.find((entry) => entry.id === id))
    .filter(Boolean);
  const compactLeadershipNav = ["部長", "副部長"].includes(currentUser?.role);
  const primaryIds = new Set(["home", "calendar", "attendance", "approvals"]);
  const items = compactLeadershipNav ? allItems.filter((item) => primaryIds.has(item.id)) : allItems;
  const moreItems = compactLeadershipNav ? allItems.filter((item) => !primaryIds.has(item.id)) : [];
  const openItem = (id) => {
    setMoreOpen(false);
    setActive(id);
  };
  return (
    <>
      {moreOpen && <button className="mobile-more-backdrop" aria-label="メニューを閉じる" onClick={() => setMoreOpen(false)} />}
      {moreOpen && <div className="mobile-more-menu" role="dialog" aria-label="その他のメニュー">
        <div className="mobile-more-head"><strong>その他のメニュー</strong><button onClick={() => setMoreOpen(false)}>閉じる</button></div>
        <div className="mobile-more-grid">
          {moreItems.map((item) => {
            const Icon = item.icon;
            return <button className={active === item.id ? "active" : ""} key={item.id} onClick={() => openItem(item.id)}>
              <span className="nav-icon-wrap"><Icon size={22} />{item.id === "notices" && unreadNotices > 0 && <span className="nav-unread-mark" />}</span>
              {item.label}
            </button>;
          })}
        </div>
      </div>}
      <nav className="bottom-nav" style={{ gridTemplateColumns: `repeat(${items.length + (compactLeadershipNav ? 1 : 0)}, minmax(0, 1fr))` }}>
        {items.map((item) => {
          const id = item.id;
          const Icon = item.icon;
          return (
            <button className={`nav-item ${active === id ? "active" : ""}`} key={id} onClick={() => openItem(id)}>
              <span className="nav-icon-wrap"><Icon size={24} />{id === "notices" && unreadNotices > 0 && <span className="nav-unread-mark" aria-label={`未読のお知らせ${unreadNotices}件`} />}</span>
              {item.label}
            </button>
          );
        })}
        {compactLeadershipNav && <button className={`nav-item ${moreOpen || moreItems.some((item) => item.id === active) ? "active" : ""}`} onClick={() => setMoreOpen((open) => !open)}>
          <Menu size={24} />
          メニュー
        </button>}
      </nav>
    </>
  );
}

function Section({ title, action, children }) {
  return (
    <section className="section">
      <div className="section-head">
        <h2 className="section-title">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function ScreenIntro({ eyebrow, title, text, action }) {
  return (
    <section className="screen-intro">
      <div>
        <div className="intro-eyebrow">{eyebrow}</div>
        <h2>{title}</h2>
        <p>{text}</p>
      </div>
      {action}
    </section>
  );
}

function Metric({ label, value, note }) {
  return (
    <div className="card metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      <div className="metric-note">{note}</div>
    </div>
  );
}

function SystemGuideContent() {
  const guideItems = [
    ["ホーム", "今日の予定、通知、次にやることを確認できます。よく使う画面はクイックメニューから開けます。"],
    ["カレンダー・出欠申請", "予定の詳細を確認し、出席・欠席・遅刻・早退を登録します。欠席などは承認後に確定します。"],
    ["お知らせ", "新しい連絡やTo Doを確認します。確認したお知らせは既読にすると未読マークが消えます。"],
    ["To Do・パート連絡", "全体や自分のパート、金管・木管に共有された作業と連絡を確認できます。"],
    ["部員一覧・マイページ", "部員の所属や係を確認できます。自分のプロフィールはマイページから編集できます。"],
    ["承認・運営", "役職者は出欠申請の承認、管理者は予定・部員・共有情報などの管理ができます。"],
  ];
  return <div className="system-guide-grid">
    {guideItems.map(([title, description]) => <div className="card system-guide-item" key={title}>
      <div className="item-title">{title}</div>
      <div className="item-note">{description}</div>
    </div>)}
  </div>;
}

function PrivacyPurposeContent() {
  return <div className="privacy-purpose-content">
    <p>BandAttendは、吹奏楽部の活動を安全かつ円滑に運営するため、必要な範囲で部員情報を利用します。</p>
    <div className="privacy-purpose-grid">
      <div><strong>利用する情報</strong><span>学籍番号、氏名、学年、誕生日、パート、役職・係、出欠と申請理由、任意で登録したプロフィール情報、最終ログイン時刻など</span></div>
      <div><strong>利用目的</strong><span>本人確認、予定と出欠の管理、申請の承認、部内連絡、To Do共有、権限管理、システムの安全な運用と改善</span></div>
      <div><strong>情報の表示範囲</strong><span>役職と権限に応じ、部員・パートリーダー・部長・副部長・管理者など、部活動の運営に必要な相手だけに表示します。</span></div>
      <div><strong>外部サービスの利用</strong><span>データの保存やシステム提供に必要なクラウドサービスを利用します。部活動の運営目的以外で個人情報を販売・利用しません。</span></div>
      <div><strong>修正・削除の相談</strong><span>登録情報の修正はマイページから行えます。削除や取り扱いに関する相談はBandAttendの管理者へ連絡してください。</span></div>
    </div>
  </div>;
}

function BirthdayCelebration({ name, onClose }) {
  const colors = ["#ef5b6c", "#496de8", "#f0c94d", "#56b88a", "#9b6be8"];
  return <div className="birthday-celebration-overlay" role="dialog" aria-modal="true" aria-labelledby="birthday-celebration-title">
    <div className="birthday-confetti" aria-hidden="true">
      {Array.from({ length: 24 }, (_, index) => <span key={index} style={{
        "--confetti-left": `${(index * 37) % 100}%`,
        "--confetti-delay": `${(index % 8) * -0.18}s`,
        "--confetti-color": colors[index % colors.length],
      }} />)}
    </div>
    <div className="birthday-celebration-card">
      <div className="birthday-cake" aria-hidden="true">🎂</div>
      <div className="intro-eyebrow">HAPPY BIRTHDAY</div>
      <h2 id="birthday-celebration-title">{name}さん<br />お誕生日おめでとう！</h2>
      <p>素敵な一年になりますように。今日の部活動も、みんなで楽しい一日にしましょう。</p>
      <button className="primary-button" onClick={onClose}>BandAttendを始める</button>
    </div>
  </div>;
}

function MaintenanceScreen() {
  return <main className="signin">
    <div className="signin-card">
      <div className="intro-eyebrow">MAINTENANCE</div>
      <h1 className="signin-title">メンテナンス中です</h1>
      <p className="signin-copy">現在、管理者がシステムの点検を行っています。終了するまでしばらくお待ちください。</p>
      <p className="item-note" style={{ textAlign: "center", marginTop: 20 }}>メンテナンスが終了すると自動的に利用できるようになります。</p>
    </div>
  </main>;
}

function EventSummaryCard({ event, onAction, bare = false, collapsibleDescription = false }) {
  const eventDate = event.date ? new Date(`${event.date}T00:00:00`) : null;
  const monthLabel = eventDate ? `${eventDate.getMonth() + 1}月` : "予定";
  const description = event.description || "";
  const shouldCollapseDescription = collapsibleDescription
    && (description.includes("\n") || description.length > 100);
  return (
    <article className={bare ? "event-summary" : "card event-summary"}>
      <div className="event-date">
        <span>{monthLabel}・{weekdayForDate(event.date)}</span>
        <strong>{event.day}</strong>
      </div>
      <div>
        <div className="event-badges">
          <span className="notice-badge">{event.type}</span>
          {event.teacherVisit && <span className="teacher-visit-label"><User size={13} />先生来校</span>}
        </div>
        <div className="item-title">{event.title}</div>
        <div className="item-note event-time"><Clock size={13} /> {event.time} / {event.place}</div>
        {shouldCollapseDescription ? (
          <details className="event-description-details">
            <summary>メモを見る</summary>
            <p className="event-description">{description}</p>
          </details>
        ) : <p className="event-description">{description}</p>}
      </div>
      {onAction && (
        <button className="small-button icon-round" onClick={onAction} aria-label="予定を開く">
          <ChevronRight size={18} />
        </button>
      )}
    </article>
  );
}

function HomeScreen({ setActive, token, currentUser }) {
  const [homeDate, setHomeDate] = useState(() => todayKey());
  const homePath = `/api/home?target_date=${homeDate}`;
  const [homeData, setHomeData] = useState(() => getCachedData(token, homePath));
  const [publications, setPublications] = useState(() => (getCachedData(token, "/api/publications")?.items || []).filter((item) => item.isPublished));
  const [fastNextPerformance, setFastNextPerformance] = useState(() => loadSavedNextPerformance());
  const [homeError, setHomeError] = useState("");
  const [homeMessage, setHomeMessage] = useState("");
  const [selectedHomeEventId, setSelectedHomeEventId] = useState("");
  const [checkedHomeMemos, setCheckedHomeMemos] = useState({});
  const [homeRefreshKey, setHomeRefreshKey] = useState(0);
  const [homeAttendanceLoading, setHomeAttendanceLoading] = useState(false);
  const [systemLinkForm, setSystemLinkForm] = useState({ name: "", description: "", url: "", iconUrl: "" });
  const [editingSystemLinkId, setEditingSystemLinkId] = useState(null);
  const [savingSystemLink, setSavingSystemLink] = useState(false);
  const [birthdayDrafts, setBirthdayDrafts] = useState({});
  const [birthdaySendingId, setBirthdaySendingId] = useState(null);
  const [sentBirthdayRecipients, setSentBirthdayRecipients] = useState({});
  const [leaveStatusResolved, setLeaveStatusResolved] = useState(false);

  useEffect(() => {
    if (!token) return;

    setLeaveStatusResolved(false);

    let ignore = false;

    fetchJsonCached(token, "/api/home/next-performance", { force: homeRefreshKey > 0 })
      .then((payload) => {
        if (ignore) return;
        const next = payload.showNextPerformance ? normalizeNextPerformance(payload.nextPerformance) : null;
        setFastNextPerformance(next);
        saveNextPerformance({ ...payload, nextPerformance: next });
      })
      .catch(() => {});

    async function loadHome() {
      setHomeError("");
      try {
        const [data, publicationData] = await Promise.all([
          fetchJsonCached(token, homePath, { force: true, errorMessage: "ホーム情報を読み込めませんでした" }),
          fetchJsonCached(token, "/api/publications", { force: homeRefreshKey > 0 }),
        ]);
        if (!ignore) {
          setHomeData(data);
          setLeaveStatusResolved(true);
          const next = data.showNextPerformance ? normalizeNextPerformance(data.nextPerformance) : null;
          setFastNextPerformance(next);
          saveNextPerformance({ showNextPerformance: data.showNextPerformance, nextPerformance: next });
          setPublications((publicationData.items || []).filter((item) => item.isPublished));
          prefetchCommonScreens(token, currentUser);
        }
      } catch (err) {
        if (!ignore) setHomeError(err.message || "ホーム情報を読み込めませんでした");
      }
    }

    loadHome();

    return () => {
      ignore = true;
    };
  }, [token, homeRefreshKey, homeDate]);

  useEffect(() => {
    const updateHomeDate = () => {
      const nextDate = todayKey();
      setHomeDate((current) => {
        if (current === nextDate) return current;
        setHomeData(null);
        return nextDate;
      });
    };
    const timer = window.setInterval(updateHomeDate, 60000);
    window.addEventListener("focus", updateHomeDate);
    document.addEventListener("visibilitychange", updateHomeDate);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", updateHomeDate);
      document.removeEventListener("visibilitychange", updateHomeDate);
    };
  }, []);

  const data = homeData || fallbackHomeData;
  const unread = data.unreadNotifications || [];
  const todayEvents = data.todayEvents || [];
  const mainEvent = todayEvents[0];
  const tasks = data.tasks || fallbackHomeData.tasks;
  const nextPerformance = homeData ? normalizeNextPerformance(data.nextPerformance) : fastNextPerformance;
  const attendanceTask = tasks.find((task) => task.key === "register_attendance");
  const ownBirthdayToday = Boolean(data.myBirthdayToday);
  const isTeacher = currentUser?.role === "顧問";

  async function sendBirthdayMessage(recipientId) {
    const message = (birthdayDrafts[recipientId] || "").trim();
    if (!message) return;
    setBirthdaySendingId(recipientId);
    setHomeError("");
    setHomeMessage("");
    try {
      const response = await fetchApi(`${API_BASE}/api/birthday-messages`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ recipientId, message }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "お祝いメッセージを送れませんでした");
      setBirthdayDrafts((current) => ({ ...current, [recipientId]: "" }));
      setSentBirthdayRecipients((current) => ({ ...current, [recipientId]: true }));
      setHomeMessage(body.message || "お祝いメッセージを送りました。");
    } catch (err) {
      setHomeError(err.message || "お祝いメッセージを送れませんでした");
    } finally {
      setBirthdaySendingId(null);
    }
  }

  async function reactToBirthdayMessage(messageId) {
    setHomeError("");
    try {
      const response = await fetchApi(`${API_BASE}/api/birthday-messages/${messageId}/reaction`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "リアクションを送れませんでした");
      setHomeData((current) => current ? {
        ...current,
        birthdayMessages: (current.birthdayMessages || []).map((item) => (
          item.id === messageId ? { ...item, reacted: true } : item
        )),
      } : current);
      invalidateCache(token, "/api/home");
    } catch (err) {
      setHomeError(err.message || "リアクションを送れませんでした");
    }
  }

  async function markHomeNotificationsRead(notificationId = null) {
    const endpoint = notificationId
      ? `${API_BASE}/api/notifications/${notificationId}/read`
      : `${API_BASE}/api/notifications/read-visible`;
    const response = await fetchApi(endpoint, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) {
      setHomeError("通知を確認済みにできませんでした");
      return;
    }
    setHomeError("");
    setHomeMessage("通知を確認済みにしました。");
    invalidateCache(token, "/api/home");
    setHomeRefreshKey((current) => current + 1);
  }

  async function submitHomeAttendance(eventId) {
    setHomeError("");
    setHomeMessage("");
    setHomeAttendanceLoading(true);
    try {
      const response = await fetchApi(`${API_BASE}/api/attendance/confirm`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ eventId }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || "出席登録できませんでした");
      }
      setHomeMessage("出席を確認しました。");
      setSelectedHomeEventId("");
      invalidateCache(token, "/api/home");
      invalidateCache(token, "/api/events");
      invalidateCache(token, "/api/attendance");
      setHomeRefreshKey((current) => current + 1);
    } catch (err) {
      setHomeError(err.message || "出席登録できませんでした");
    } finally {
      setHomeAttendanceLoading(false);
    }
  }

  async function submitHomeLateAttendance(eventId) {
    setHomeError("");
    setHomeMessage("");
    setHomeAttendanceLoading(true);
    try {
      const response = await fetchApi(`${API_BASE}/api/attendance`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          eventId,
          status: "遅刻",
          reason: "ホームの練習メモ確認から遅刻で参加",
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || "遅刻申請できませんでした");
      }
      setHomeMessage("遅刻で参加する申請を送信しました。");
      setSelectedHomeEventId("");
      invalidateCache(token, "/api/home");
      invalidateCache(token, "/api/events");
      invalidateCache(token, "/api/attendance");
      setHomeRefreshKey((current) => current + 1);
    } catch (err) {
      setHomeError(err.message || "遅刻申請できませんでした");
    } finally {
      setHomeAttendanceLoading(false);
    }
  }

  function editSystemLink(link) {
    setEditingSystemLinkId(link.id);
    setSystemLinkForm({ name: link.name, description: link.description, url: link.url, iconUrl: link.iconUrl || "" });
    setHomeError(""); setHomeMessage("");
  }

  function resetSystemLinkForm() {
    setEditingSystemLinkId(null);
    setSystemLinkForm({ name: "", description: "", url: "", iconUrl: "" });
  }

  async function saveSystemLink(event) {
    event.preventDefault();
    setSavingSystemLink(true); setHomeError(""); setHomeMessage("");
    try {
      const response = await fetchApi(`${API_BASE}/api/admin/external-system-links${editingSystemLinkId ? `/${editingSystemLinkId}` : ""}`, {
        method: editingSystemLinkId ? "PATCH" : "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify(systemLinkForm),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "関連システムを保存できませんでした");
      setHomeMessage(editingSystemLinkId ? "関連システムを更新しました。" : "関連システムを追加しました。");
      resetSystemLinkForm();
      invalidateCache(token, "/api/home");
      setHomeRefreshKey((current) => current + 1);
    } catch (err) {
      setHomeError(err.message || "関連システムを保存できませんでした");
    } finally {
      setSavingSystemLink(false);
    }
  }

  async function removeSystemLink(link) {
    if (!window.confirm(`${link.name}のリンクを削除しますか？`)) return;
    setHomeError(""); setHomeMessage("");
    const response = await fetchApi(`${API_BASE}/api/admin/external-system-links/${link.id}`, {
      method: "DELETE", headers: { Authorization: `Bearer ${token}` },
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      setHomeError(body.detail || "関連システムを削除できませんでした");
      return;
    }
    setHomeMessage("関連システムを削除しました。");
    if (editingSystemLinkId === link.id) resetSystemLinkForm();
    invalidateCache(token, "/api/home");
    setHomeRefreshKey((current) => current + 1);
  }

  function openQuickMenu(target) {
    setActive(target);
    window.requestAnimationFrame(() => {
      window.scrollTo({ top: 0, left: 0, behavior: "auto" });
    });
  }

  return (
    <>
      <div className={`home-welcome ${ownBirthdayToday ? "birthday-home-welcome" : ""}`}>
        <div>
          <div className="intro-eyebrow">BANDATTEND</div>
          <h2>{currentUser?.name}さん、おかえりなさい</h2>
          <p>{ownBirthdayToday ? "お誕生日おめでとうございます。素敵な一日を過ごしてください！" : "今日の活動と、次に必要なことをここから確認できます。"}</p>
        </div>
        {ownBirthdayToday && <span className="birthday-home-ribbon">🎉 HAPPY BIRTHDAY</span>}
      </div>
      {homeError && <div className="card error-card">{homeError}</div>}
      {homeMessage && <div className="card success-card">{homeMessage}</div>}

      {nextPerformance && (
        <div className="hero-card">
          <div className="hero-label">次の本番</div>
          <div className="hero-value">{nextPerformance.label}</div>
          <div className="hero-note">{nextPerformance.title} / {formatDateWithWeekday(nextPerformance.date)} / {nextPerformance.location}</div>
        </div>
      )}

      <Section
        title="今日の予定"
        action={todayEvents.length > 1 && (
          <span className="item-note">{todayEvents.length}件</span>
        )}
      >
        {mainEvent ? (
          <div className="today-schedule-list">
            {todayEvents.map((event) => (
              <article
                className={`today-schedule-card ${String(event.id) === String(selectedHomeEventId) ? "is-open" : ""}`}
                key={event.id}
              >
                <button
                  type="button"
                  className="today-schedule-bar"
                  aria-expanded={String(event.id) === String(selectedHomeEventId)}
                  onClick={() => setSelectedHomeEventId((current) => (
                    String(current) === String(event.id) ? "" : String(event.id)
                  ))}
                >
                  <span className="today-schedule-date">{event.day}<small>{weekdayForDate(event.date)}曜</small></span>
                  <span className="today-schedule-summary">
                    <strong>{event.title}</strong>
                    <small><Clock size={13} />{event.time} / {event.place}</small>
                  </span>
                  <ChevronDown className="today-schedule-chevron" size={20} />
                </button>

                {String(event.id) === String(selectedHomeEventId) && (
                  <div className="today-schedule-detail">
                    <div className="today-schedule-memo">
                      <div className="item-title">今日の予定・メモ</div>
                      <div className="item-note">{event.description || "メモはありません。"}</div>
                    </div>
                    {event.myAttendance ? (
                      <div className="card success-card">
                        登録済み：{event.myAttendance.status}（{event.myAttendance.approvalStatus}）
                      </div>
                    ) : currentUser?.permissions?.canSubmitAttendance ? (
                      <>
                        <label className="today-memo-check item-note">
                          <input
                            type="checkbox"
                            checked={Boolean(checkedHomeMemos[event.id])}
                            onChange={(changeEvent) => setCheckedHomeMemos((current) => ({
                              ...current,
                              [event.id]: changeEvent.target.checked,
                            }))}
                          />
                          メモの内容を確認しました
                        </label>
                        <div className="event-form-actions">
                          <button
                            className="primary-button"
                            disabled={!checkedHomeMemos[event.id] || homeAttendanceLoading}
                            onClick={() => submitHomeAttendance(event.id)}
                          >
                            出席する
                          </button>
                          <button
                            className="ghost-button"
                            disabled={!checkedHomeMemos[event.id] || homeAttendanceLoading}
                            onClick={() => submitHomeLateAttendance(event.id)}
                          >
                            遅刻で参加
                          </button>
                        </div>
                        <div className="item-note today-schedule-help">
                          欠席する場合は「出欠申請」から申請してください。
                        </div>
                      </>
                    ) : (
                      <div className="item-note">出席登録対象の役職ではありません。</div>
                    )}
                  </div>
                )}
              </article>
            ))}
          </div>
        ) : (
          <div className="card empty-card">
            <div className="item-title">今日の予定はありません</div>
            <div className="item-note">予定が追加されると、ここに練習や本番の内容が表示されます。</div>
          </div>
        )}
      </Section>

      <Section title="今日の概要">
        <div className="grid two desktop-grid">
          <Metric
            label="今日の予定"
            value={todayEvents.length > 0 ? "予定があります" : "今日の予定はありません"}
            note={mainEvent ? mainEvent.title : "予定なし"}
          />
          <Metric label="未読通知" value={`${unread.length}件`} note={unread.length ? "確認してください" : "未読なし"} />
          {!isTeacher && <Metric label="出欠申請" value={attendanceTask?.completed ? "完了" : "未完了"} note={mainEvent ? "今日の予定に回答" : "予定なし"} />}
          {!isTeacher && leaveStatusResolved && (data.leaveCredits?.enabled !== false || currentUser?.role === "管理者") && (
            <Metric
              label="休暇権利"
              value={data.leaveCredits?.enabled === false ? "使用不可" : `${data.leaveCredits?.available || 0}回`}
              note={data.leaveCredits?.enabled === false ? "機能停止中" : "使用可能"}
            />
          )}
        </div>
      </Section>

      {!isTeacher && <Section title="今月の出席（今日まで）">
        <AttendanceOverview stats={data.attendanceStats} compact />
      </Section>}

      {publications.length > 0 && (
        <Section title="公開されたランキング・統計">
          <PublicationCards items={publications} />
        </Section>
      )}

      <Section title="今日の誕生日">
        <div className="birthday-card">
          {!data.birthdaysAreToday && (
            <div className="birthday-empty-title">今日の誕生日はいません。</div>
          )}
          {!data.birthdaysAreToday && data.birthdayDate && (
            <div className="item-title">次の誕生日：{formatDateWithWeekday(data.birthdayDate)}</div>
          )}
          {(data.birthdays || []).length === 0 && (
            <div className="item-note">誕生日が登録されている部員はいません。</div>
          )}
          {(data.birthdays || []).map((member) => (
            <div className="birthday-person-wrap" key={member.id || member.name}>
              <div className="birthday-person">
                <div className="birthday-avatar">{member.name.slice(0, 1)}</div>
                <div>
                  <div className="item-title">{member.name}</div>
                  <div className="item-note">{member.part} / {member.grade}年</div>
                </div>
              </div>
              {data.birthdaysAreToday && Number(member.id) !== Number(currentUser?.id) && (
                sentBirthdayRecipients[member.id] || (data.sentBirthdayMessageRecipientIds || []).includes(Number(member.id)) ? (
                  <div className="success-card">
                    送信済みです
                    {(data.sentBirthdayMessages || []).find((item) => Number(item.recipientId) === Number(member.id))?.reacted && <span className="birthday-reaction-received"> ★</span>}
                  </div>
                ) : (
                  <div className="birthday-message-form">
                    <input
                      className="input"
                      maxLength={80}
                      placeholder={`${member.name}さんへお祝いメッセージ（80文字以内）`}
                      value={birthdayDrafts[member.id] || ""}
                      onChange={(event) => setBirthdayDrafts((current) => ({ ...current, [member.id]: event.target.value }))}
                    />
                    <button className="small-button" disabled={birthdaySendingId === member.id || !(birthdayDrafts[member.id] || "").trim()} onClick={() => sendBirthdayMessage(member.id)}>
                      {birthdaySendingId === member.id ? "送信中" : "送る"}
                    </button>
                  </div>
                )
              )}
            </div>
          ))}
          {ownBirthdayToday && (
            <div className="birthday-letter-board">
              <div className="item-title">みんなからのお祝い</div>
              {(data.birthdayMessages || []).length === 0 && <div className="item-note">お祝いメッセージが届くと、ここに表示されます。</div>}
              {(data.birthdayMessages || []).map((item) => (
                <div className="birthday-letter" key={item.id}>
                  <p>{item.message}</p>
                  <div className="birthday-letter-footer">
                    <span>{item.senderName}さん・{item.senderPart}</span>
                    <button
                      className={`birthday-star-button ${item.reacted ? "reacted" : ""}`}
                      disabled={item.reacted}
                      onClick={() => reactToBirthdayMessage(item.id)}
                      aria-label={item.reacted ? "星を送りました" : `${item.senderName}さんに星を送る`}
                    >
                      {item.reacted ? "★" : "☆"}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </Section>

      <Section title="ホーム通知" action={unread.length > 0 ? <button className="small-button" onClick={() => markHomeNotificationsRead()}>確認済み</button> : <button className="small-button" onClick={() => setActive("notices")}>一覧</button>}>
        <div className="list">
          {unread.map((notice) => (
            <button className="card alert-row" key={notice.id} onClick={() => markHomeNotificationsRead(notice.id)}>
              <span className="notice-badge important">
                未読
              </span>
              <span>
                <span className="item-title">{notice.title}</span>
                <span className="item-note">{notice.message}</span>
              </span>
            </button>
          ))}
          {unread.length === 0 && (
            <div className="card empty-card">
              <div className="item-title">未読通知はありません</div>
              <div className="item-note">承認結果やお知らせが届くとここに表示されます。</div>
            </div>
          )}
        </div>
      </Section>

      <div className={isTeacher ? "" : "content-grid"}>
        {!isTeacher && <Section title={data.taskHasEvents ? `${formatDateWithWeekday(data.taskDate || homeDate)}にやること` : "次にやること"}>
          <TaskList compact tasks={tasks} />
        </Section>}
        <Section title={isTeacher ? "先生用クイックメニュー" : "クイックメニュー"}>
          <div className="quick-menu-grid">
            {isTeacher ? <>
              <button className="quick-menu-card quick-menu-publication" onClick={() => openQuickMenu("notices")}>
                <span className="quick-menu-icon"><Bell size={24} /></span>
                <span><strong>お知らせ</strong><small>部員への連絡を送る</small></span>
                <ChevronRight size={20} />
              </button>
              <button className="quick-menu-card quick-menu-contact" onClick={() => openQuickMenu("calendar")}>
                <span className="quick-menu-icon"><CalendarDays size={24} /></span>
                <span><strong>カレンダー</strong><small>練習と本番を確認</small></span>
                <ChevronRight size={20} />
              </button>
              <button className="quick-menu-card quick-menu-ranking" onClick={() => openQuickMenu("statistics")}>
                <span className="quick-menu-icon"><Trophy size={24} /></span>
                <span><strong>出席・統計</strong><small>部全体の状況を確認</small></span>
                <ChevronRight size={20} />
              </button>
              <button className="quick-menu-card quick-menu-todo" onClick={() => openQuickMenu("members")}>
                <span className="quick-menu-icon"><Users size={24} /></span>
                <span><strong>部員一覧</strong><small>所属とプロフィールを確認</small></span>
                <ChevronRight size={20} />
              </button>
            </> : <>
            <button className="quick-menu-card quick-menu-todo" onClick={() => openQuickMenu("tasks")}>
              <span className="quick-menu-icon"><ListTodo size={24} /></span>
              <span><strong>To Do</strong><small>共有タスクを確認</small></span>
              <ChevronRight size={20} />
            </button>
            <button className="quick-menu-card quick-menu-contact" onClick={() => openQuickMenu("contact")}>
              <span className="quick-menu-icon"><MessageCircle size={24} /></span>
              <span><strong>パート連絡</strong><small>パート内の連絡を見る</small></span>
              <ChevronRight size={20} />
            </button>
            <button className="quick-menu-card quick-menu-ranking" onClick={() => openQuickMenu("ranking")}>
              <span className="quick-menu-icon"><Trophy size={24} /></span>
              <span><strong>ランキング</strong><small>個人・パート順位を見る</small></span>
              <ChevronRight size={20} />
            </button>
            {currentUser?.role === "管理者" && (
              <button className="quick-menu-card quick-menu-publication" onClick={() => openQuickMenu("publications")}>
                <span className="quick-menu-icon"><Bell size={24} /></span>
                <span><strong>公開設定</strong><small>統計・ランキングを公開</small></span>
                <ChevronRight size={20} />
              </button>
            )}
            </>}
          </div>
        </Section>
      </div>
      {!isTeacher && <Section title="関連システム">
        <div className="grid two wide-grid">
          {(data.externalSystemLinks || []).map((link) => (
            <div className="card external-system-card" key={link.id}>
              <a href={link.url} target="_blank" rel="noopener noreferrer" className="external-system-link">
                <div className="external-system-head">
                  {link.iconUrl && <img className="external-system-icon" src={link.iconUrl} alt="" loading="lazy" />}
                  <div><div className="item-title">{link.name}</div><div className="item-note">{link.description}</div></div>
                </div>
                <div className="external-system-url">サイトを開く →</div>
              </a>
              {currentUser?.role === "管理者" && <div className="external-system-actions">
                <button className="small-button" onClick={() => editSystemLink(link)}>編集</button>
                <button className="small-button danger-button" onClick={() => removeSystemLink(link)}>削除</button>
              </div>}
            </div>
          ))}
        </div>
        {(data.externalSystemLinks || []).length === 0 && currentUser?.role !== "管理者" && <div className="card empty-card">関連システムはまだ登録されていません。</div>}
        {currentUser?.role === "管理者" && <form className="card form-stack external-system-form" onSubmit={saveSystemLink}>
          <div className="item-title">{editingSystemLinkId ? "関連システムを編集" : "関連システムを追加"}</div>
          <input className="input" required placeholder="システム名" value={systemLinkForm.name} onChange={(event) => setSystemLinkForm({ ...systemLinkForm, name: event.target.value })} />
          <textarea className="input" required rows={3} placeholder="システムの内容・説明" value={systemLinkForm.description} onChange={(event) => setSystemLinkForm({ ...systemLinkForm, description: event.target.value })} />
          <input className="input" required type="url" placeholder="https://example.com" value={systemLinkForm.url} onChange={(event) => {
            const url = event.target.value;
            setSystemLinkForm({ ...systemLinkForm, url, iconUrl: systemLinkForm.iconUrl || suggestedExternalSystemIcon(url) });
          }} />
          <input className="input" type="url" placeholder="アイコン画像URL（任意）" value={systemLinkForm.iconUrl} onChange={(event) => setSystemLinkForm({ ...systemLinkForm, iconUrl: event.target.value })} />
          {systemLinkForm.iconUrl && <div className="external-system-icon-preview"><img src={systemLinkForm.iconUrl} alt="アイコンのプレビュー" /><span className="item-note">アイコンのプレビュー</span></div>}
          <div className="event-form-actions">
            <button className="primary-button" disabled={savingSystemLink}>{savingSystemLink ? "保存中" : editingSystemLinkId ? "更新する" : "リンクを追加"}</button>
            {editingSystemLinkId && <button type="button" className="ghost-button" onClick={resetSystemLinkForm}>キャンセル</button>}
          </div>
        </form>}
      </Section>}
      <Section title="BandAttend説明書">
        <details className="card system-guide-details">
          <summary>システムの使い方を見る</summary>
          <p className="item-note">BandAttendでよく使う機能と基本的な操作をまとめています。</p>
          <SystemGuideContent />
        </details>
      </Section>
      <Section title="個人情報の取り扱い">
        <details className="card system-guide-details privacy-details">
          <summary>個人情報の利用目的を見る</summary>
          <PrivacyPurposeContent />
        </details>
      </Section>
    </>
  );
}

function TaskList({ compact = false, tasks = [] }) {
  return (
    <div className="list">
      {tasks.slice(0, compact ? 3 : tasks.length).map((task) => (
        <div className="card list-item" key={task.key}>
          <span className={`check ${task.completed ? "done" : ""}`}>
            {task.completed && <Check size={16} />}
          </span>
          <div>
            <div className="item-title">{task.label}</div>
            <div className="item-note">{task.note}</div>
          </div>
          <span className="notice-badge">{task.completed ? "完了" : "未完了"}</span>
        </div>
      ))}
      {tasks.length === 0 && (
        <div className="card empty-card">今日やることはありません。</div>
      )}
    </div>
  );
}

function TasksScreen({ token, currentUser, onUnreadNoticesChange }) {
  const [items, setItems] = useState(() => getCachedData(token, "/api/todos")?.items || []);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("演奏");
  const [scope, setScope] = useState("全体");
  const canSendPartTodo = partOptions.includes(currentUser?.part);

  async function loadTodos(force = false) {
    try {
      const data = await fetchJsonCached(token, "/api/todos", { force });
      setItems(data.items || []);
    } catch {
      // 前回表示できた内容を残し、画面切り替えを止めない。
    }
  }

  useEffect(() => {
    if (token) {
      loadTodos();
    }
  }, [token]);

  async function addTodo() {
    if (!title.trim()) return;
    const response = await fetchApi(`${API_BASE}/api/todos`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ scope, part: scope === "パート" ? currentUser?.part : null, category, title }),
    });
    if (!response.ok) return;
    setTitle("");
    invalidateCache(token, "/api/home");
    invalidateCache(token, "/api/announcements");
    const isCurrentUserTarget = scope === "全体"
      || (scope === "パート" && canSendPartTodo)
      || (scope === "木管" && ["フルート", "クラリネット", "サックス"].includes(currentUser?.part))
      || (scope === "金管" && ["トランペット", "ホルン", "トロンボーン", "ユーフォニアム", "バスパート"].includes(currentUser?.part));
    if (isCurrentUserTarget) onUnreadNoticesChange?.((current) => current + 1);
    invalidateCache(token, "/api/todos");
    loadTodos(true);
  }

  async function toggleTodo(id) {
    const response = await fetchApi(`${API_BASE}/api/todos/${id}/toggle`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) return;
    invalidateCache(token, "/api/todos");
    invalidateCache(token, "/api/home");
    loadTodos(true);
  }

  async function removeTodo(todo) {
    if (!window.confirm(`完了済みの「${todo.title}」を削除しますか？`)) return;
    const response = await fetchApi(`${API_BASE}/api/todos/${todo.id}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) return;
    invalidateCache(token, "/api/home");
    invalidateCache(token, "/api/todos");
    loadTodos(true);
  }

  return (
    <>
      <ScreenIntro
        eyebrow="TODO"
        title="To Do"
        text="全体・パート・金管・木管ごとに、共有するやることを管理します。"
      />
      <Section title="To Doを追加">
        <div className="card inline-form">
          <select className="input" value={scope} onChange={(event) => setScope(event.target.value)}>
            {["全体", ...(canSendPartTodo ? ["パート"] : []), "金管", "木管"].map((item) => <option key={item}>{item}</option>)}
          </select>
          {scope === "パート" && <div className="item-note">送信先：{currentUser?.part}</div>}
          <select className="input" value={category} onChange={(event) => setCategory(event.target.value)}>
            {["演奏", "事務", "準備", "その他"].map((item) => <option key={item}>{item}</option>)}
          </select>
          <input className="input" placeholder="やることを入力" value={title} onChange={(event) => setTitle(event.target.value)} />
          <button className="primary-button" onClick={addTodo}>追加</button>
        </div>
      </Section>
      {["全体", "パート", "金管", "木管"].map((group) => {
        const groupItems = items.filter((todo) => todo.scope === group);
        return <Section title={`${group} To Do`} key={group}>
          <div className="list">
            {groupItems.map((todo, index) => (
              <div className={`card list-item ${todo.completed ? "completed-item" : ""}`} key={todo.id}>
                <span className="todo-index">{index + 1}</span>
                <div>
                  <div className="item-title">{todo.title}</div>
                  <div className="item-note">{todo.category} / {todo.scope === "パート" ? `${todo.part} / ` : ""}記入: {todo.created_by}</div>
                </div>
                {todo.completed && <span className="notice-badge">完了済み</span>}
                <button className="small-button" onClick={() => toggleTodo(todo.id)}>{todo.completed ? "戻す" : "完了"}</button>
                {todo.completed && todo.canDelete && <button className="small-button danger-button" onClick={() => removeTodo(todo)}>削除</button>}
              </div>
            ))}
            {groupItems.length === 0 && <div className="card empty-card">{group}向けのTo Doはありません。</div>}
          </div>
        </Section>;
      })}
    </>
  );
}

function PracticeReflectionPanel({ token, event }) {
  const [data, setData] = useState({ items: [], availableScopes: ["全体"] });
  const [form, setForm] = useState({ targetScope: "全体", title: "", content: "" });
  const [editingId, setEditingId] = useState(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function load() {
    const response = await fetchApi(`${API_BASE}/api/events/${event.id}/reflections`, { headers: { Authorization: `Bearer ${token}` } });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "振り返りを読み込めませんでした");
    setData(payload);
  }

  useEffect(() => {
    setEditingId(null);
    setForm({ targetScope: "全体", title: "", content: "" });
    setMessage(""); setError("");
    load().catch((err) => setError(err.message));
  }, [event.id, token]);

  async function save() {
    setMessage(""); setError("");
    const url = editingId ? `${API_BASE}/api/events/${event.id}/reflections/${editingId}` : `${API_BASE}/api/events/${event.id}/reflections`;
    const response = await fetchApi(url, {
      method: editingId ? "PATCH" : "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) { setError(payload.detail || "保存できませんでした"); return; }
    setForm({ targetScope: "全体", title: "", content: "" }); setEditingId(null);
    setMessage(editingId ? "振り返りを更新しました。" : "振り返りを投稿しました。");
    load().catch((err) => setError(err.message));
  }

  function startEdit(item) {
    setEditingId(item.id);
    setForm({ targetScope: item.targetScope, title: item.title, content: item.content });
    setMessage(""); setError("");
  }

  async function remove(item) {
    if (!window.confirm("この振り返りを削除しますか？")) return;
    const response = await fetchApi(`${API_BASE}/api/events/${event.id}/reflections/${item.id}`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) { const payload = await response.json().catch(() => ({})); setError(payload.detail || "削除できませんでした"); return; }
    if (editingId === item.id) { setEditingId(null); setForm({ targetScope: "全体", title: "", content: "" }); }
    setMessage("振り返りを削除しました。"); load().catch((err) => setError(err.message));
  }

  return <div className="practice-reflection-panel card-action">
    <div className="practice-reflection-heading"><div><div className="item-title">この日の振り返り・共有事項</div><div className="item-note">欠席した人も、練習後に決まったことや注意点を確認できます。</div></div><span className="notice-badge">{data.items.length}件</span></div>
    {error && <div className="error-card">{error}</div>}{message && <div className="success-card">{message}</div>}
    <div className="practice-reflection-list">{data.items.map((item) => <div className="practice-reflection-item" key={item.id}>
      <div className="practice-reflection-meta"><span className="notice-badge">{item.targetScope}</span><span>{item.createdBy}</span></div>
      <div className="item-title">{item.title}</div><div className="practice-reflection-content">{item.content}</div>
      {item.canEdit && <div className="managed-event-actions"><button className="small-button" onClick={() => startEdit(item)}>編集</button><button className="small-button danger-button" onClick={() => remove(item)}>削除</button></div>}
    </div>)}</div>
    {data.items.length === 0 && <div className="empty-card">まだ振り返りはありません。最初の共有事項を投稿できます。</div>}
    <div className="practice-reflection-form">
      <div className="item-title">{editingId ? "自分の投稿を編集" : "振り返りを投稿"}</div>
      <label className="field-label">公開範囲<select className="input" value={form.targetScope} onChange={(change) => setForm({...form, targetScope: change.target.value})}>{(data.availableScopes || []).map((scope) => <option value={scope} key={scope}>{scope}</option>)}</select></label>
      <label className="field-label">タイトル<input className="input" value={form.title} onChange={(change) => setForm({...form, title: change.target.value})} placeholder="例：次回までに確認すること" /></label>
      <label className="field-label">内容<textarea className="input textarea" value={form.content} onChange={(change) => setForm({...form, content: change.target.value})} placeholder="練習の振り返り、変更点、次回までの課題など" /></label>
      <div className="event-form-actions"><button className="primary-button" onClick={save}>{editingId ? "更新する" : "投稿する"}</button>{editingId && <button className="ghost-button" onClick={() => { setEditingId(null); setForm({ targetScope: "全体", title: "", content: "" }); }}>編集をやめる</button>}</div>
    </div>
  </div>;
}

function CalendarScreen({ token, currentUser, setActive }) {
  const today = new Date();
  const todayMonth = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
  const [selectedMonth, setSelectedMonth] = useState(todayMonth);
  const [calendarData, setCalendarData] = useState(() => getCachedData(token, `/api/events?month=${todayMonth}`));
  const [calendarError, setCalendarError] = useState("");
  const [attendanceMessage, setAttendanceMessage] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [checkedMemos, setCheckedMemos] = useState({});
  const [selectedDay, setSelectedDay] = useState(null);
  const nowTime = `${String(today.getHours()).padStart(2, "0")}:${String(today.getMinutes()).padStart(2, "0")}`;

  function moveMonth(offset) {
    const [currentYear, currentMonth] = selectedMonth.split("-").map(Number);
    const target = new Date(currentYear, currentMonth - 1 + offset, 1);
    setSelectedMonth(`${target.getFullYear()}-${String(target.getMonth() + 1).padStart(2, "0")}`);
    setSelectedDay(null);
  }

  useEffect(() => {
    if (!token) return;

    let ignore = false;

    async function loadEvents() {
      setCalendarError("");
      try {
        const data = await fetchJsonCached(token, `/api/events?month=${selectedMonth}`, { force: refreshKey > 0, errorMessage: "予定を読み込めませんでした" });
        if (!ignore) setCalendarData(data);
      } catch (err) {
        if (!ignore) setCalendarError(err.message || "予定を読み込めませんでした");
      }
    }

    loadEvents();

    return () => {
      ignore = true;
    };
  }, [token, refreshKey, selectedMonth]);

  async function confirmAttendance(eventId) {
    setCalendarError("");
    setAttendanceMessage("");

    try {
      const response = await fetchApi(`${API_BASE}/api/attendance/confirm`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ eventId }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "出席登録できませんでした");
      }

      setAttendanceMessage("出席を確認しました。");
      invalidateCache(token, "/api/events");
      invalidateCache(token, "/api/home");
      invalidateCache(token, "/api/attendance");
      setRefreshKey((current) => current + 1);
    } catch (err) {
      setCalendarError(err.message || "出席登録できませんでした");
    }
  }

  async function submitLateAttendance(eventId) {
    setCalendarError("");
    setAttendanceMessage("");

    try {
      const response = await fetchApi(`${API_BASE}/api/attendance`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          eventId,
          status: "遅刻",
          reason: "カレンダーの遅刻者用参加ボタンから申請",
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || "遅刻申請できませんでした");
      }

      setAttendanceMessage("遅刻で参加する申請を送信しました。");
      invalidateCache(token, "/api/events");
      invalidateCache(token, "/api/home");
      invalidateCache(token, "/api/attendance");
      setRefreshKey((current) => current + 1);
    } catch (err) {
      setCalendarError(err.message || "遅刻申請できませんでした");
    }
  }

  async function cancelCalendarAttendance(event) {
    const attendance = event.myAttendance;
    if (!attendance) {
      setCalendarError("キャンセルする申請が見つかりませんでした。カレンダーを再読み込みしてください。");
      return;
    }
    if (!window.confirm(`${formatDateWithWeekday(event.date)}の${attendance.status}申請をキャンセルしますか？`)) return;
    setCalendarError("");
    setAttendanceMessage("");
    try {
      const response = await fetchApi(`${API_BASE}/api/attendance/event/${event.id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "申請をキャンセルできませんでした");
      setAttendanceMessage(data.message || "出欠申請をキャンセルしました。");
      ["/api/events", "/api/home", "/api/attendance", "/api/approvals", "/api/leave-credits"].forEach((path) => invalidateCache(token, path));
      setRefreshKey((current) => current + 1);
    } catch (err) {
      setCalendarError(err.message || "申請をキャンセルできませんでした");
    }
  }

  const [year, month] = selectedMonth.split("-").map(Number);
  const daysInMonth = new Date(year, month, 0).getDate();
  const firstWeekday = new Date(`${selectedMonth}-01T00:00:00`).getDay();
  const days = Array.from({ length: daysInMonth }, (_, index) => index + 1);
  const monthEvents = calendarData?.events || [];
  const eventDays = new Set(monthEvents.map((event) => event.day));
  const teacherVisitDays = new Set(monthEvents.filter((event) => event.teacherVisit).map((event) => event.day));
  const ownApprovedAttendanceByDay = new Map();
  monthEvents.forEach((event) => {
    if (
      event.myAttendance?.approvalStatus === "承認済み"
      && ["欠席", "遅刻", "早退"].includes(event.myAttendance.status)
      && !ownApprovedAttendanceByDay.has(event.day)
    ) {
      ownApprovedAttendanceByDay.set(event.day, event.myAttendance.status);
    }
  });
  const selectedEvents = monthEvents.filter((event) => event.day === selectedDay);
  const blanks = Array.from({ length: firstWeekday }, (_, index) => index);
  return (
    <>
      {calendarError && <div className="card error-card">{calendarError}</div>}
      {attendanceMessage && <div className="card success-card">{attendanceMessage}</div>}
      <ScreenIntro
        eyebrow={`${year}.${String(month).padStart(2, "0")}`}
        title="カレンダー"
        text="予定がある日は色付きで表示されます。日付を選ぶと、その日の練習内容と出席ボタンが出ます。"
        action={currentUser?.permissions?.canEditEvents && (
          <button className="primary-button" onClick={() => setActive("event-management")}>
            予定を追加・編集
          </button>
        )}
      />
      <Section title="カレンダー">
        <div className="calendar-month-toolbar">
          <div className="calendar-month-nav">
            <button className="calendar-month-button" aria-label="前の月" onClick={() => moveMonth(-1)}>
              <ChevronLeft size={22} />
            </button>
            <input
              className="month-input"
              type="month"
              value={selectedMonth}
              onChange={(event) => {
                setSelectedMonth(event.target.value);
                setSelectedDay(null);
              }}
            />
            <button className="calendar-month-button" aria-label="次の月" onClick={() => moveMonth(1)}>
              <ChevronRight size={22} />
            </button>
          </div>
        </div>
      </Section>
      <div className="card calendar-card">
        <div className="calendar-grid">
          {["日", "月", "火", "水", "木", "金", "土"].map((day) => (
            <div className="weekday" key={day}>{day}</div>
          ))}
          {blanks.map((blank) => (
            <div className="day blank" key={`blank-${blank}`} />
          ))}
          {days.map((day) => (
            <button
              className={`day ${selectedMonth === todayMonth && day === today.getDate() ? "today" : ""} ${eventDays.has(day) ? "has-event" : ""} ${selectedDay === day ? "selected" : ""}`}
              key={day}
              onClick={() => setSelectedDay((current) => current === day ? null : day)}
            >
              <span>{day}</span>
              {teacherVisitDays.has(day) && <span className="teacher-visit-mark" aria-label="先生来校" title="先生来校"><User size={13} /></span>}
              {eventDays.has(day) && !ownApprovedAttendanceByDay.has(day) && <span className="event-chip">{monthEvents.find((event) => event.day === day)?.type}</span>}
              {ownApprovedAttendanceByDay.has(day) && (
                <span className={`calendar-attendance-mark status-${ownApprovedAttendanceByDay.get(day)}`}>
                  {ownApprovedAttendanceByDay.get(day)}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>
      {selectedDay !== null && <Section title={`${month}/${selectedDay}（${weekdayForDate(`${selectedMonth}-${String(selectedDay).padStart(2, "0")}`)}）の予定`}>
        <div className="list">
          {selectedEvents.length === 0 && (
            <div className="card empty-card">
              <div className="item-title">予定はありません</div>
              <div className="item-note">予定が追加されると、この日に表示されます。</div>
            </div>
          )}
          {selectedEvents.map((event) => (
            <div className="card event-card" key={event.id}>
              <EventSummaryCard event={event} bare />
              <details className="calendar-approved-absence" open={(event.approvedAbsences || []).length > 0 && (event.approvedAbsences || []).length <= 5}>
                <summary>
                  <span>承認済みの欠席・遅刻・早退</span>
                  <strong>{(event.approvedAbsences || []).length}人</strong>
                </summary>
                {(event.approvedAbsences || []).length > 0 ? (
                  <div className="calendar-approved-absence-list">
                    {event.approvedAbsences.map((person, index) => (
                      <div key={`${event.id}-${person.name}-${person.status}-${index}`}>
                        <span className={`notice-badge attendance-status-${person.status}`}>{person.status}</span>
                        <span><strong>{person.name}</strong><small>{person.part}</small></span>
                      </div>
                    ))}
                  </div>
                ) : <div className="item-note calendar-approved-empty">承認済みの欠席・遅刻・早退者はいません。</div>}
              </details>
              {(event.date < todayKey() || (event.date === todayKey() && (!event.endTime || event.endTime <= nowTime))) && <PracticeReflectionPanel token={token} event={event} />}
              {event.canAttendToday && !event.myAttendance && (
                <>
                  <label className="card-action item-note" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <input
                      type="checkbox"
                      checked={Boolean(checkedMemos[event.id])}
                      onChange={(changeEvent) => setCheckedMemos((current) => ({
                        ...current,
                        [event.id]: changeEvent.target.checked,
                      }))}
                    />
                    練習メモの内容を確認しました
                  </label>
                  <div className="event-form-actions" style={{ marginTop: 12 }}>
                    <button className="primary-button" disabled={!checkedMemos[event.id]} onClick={() => confirmAttendance(event.id)}>
                      出席する
                    </button>
                    <button className="ghost-button" disabled={!checkedMemos[event.id]} onClick={() => submitLateAttendance(event.id)}>
                      遅刻で参加
                    </button>
                  </div>
                  <div className="item-note card-action">
                    欠席する場合はこのボタンは押さず、「出欠申請」から欠席申請を送ってください。
                  </div>
                </>
              )}
              {event.myAttendance && (
                <div className="card-action own-calendar-attendance">
                  <span className={`notice-badge attendance-status-${event.myAttendance.status}`}>{event.myAttendance.status}</span>
                  <div className="item-title">あなたの申請：{event.myAttendance.status}（{event.myAttendance.approvalStatus}）</div>
                  {["欠席", "遅刻", "早退"].includes(event.myAttendance.status) && event.date >= todayKey() && (
                    <button className="small-button danger-button card-action" onClick={() => cancelCalendarAttendance(event)}>
                      申請をキャンセル
                    </button>
                  )}
                </div>
              )}
              {currentUser?.permissions?.canEditEvents && (
                <button className="small-button card-action" onClick={() => setActive("event-management")}>
                  この予定を編集
                </button>
              )}
            </div>
          ))}
        </div>
      </Section>}
    </>
  );
}

function AttendanceScreen({ token, currentUser }) {
  const [status, setStatus] = useState("出席");
  const cachedTargets = getCachedData(token, "/api/attendance/targets");
  const [events, setEvents] = useState(cachedTargets?.events || []);
  const [selectedEventId, setSelectedEventId] = useState(cachedTargets?.events?.[0]?.id ? String(cachedTargets.events[0].id) : "");
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [leaveData, setLeaveData] = useState({ enabled: false, available: 0, credits: [] });
  const selectedEvent = events.find((event) => String(event.id) === String(selectedEventId)) || events[0];
  const canSubmitAttendanceStatus = Boolean(selectedEvent?.canSelectAttendance);
  const statusOptions = canSubmitAttendanceStatus ? ["出席", "欠席", "遅刻", "早退"] : ["欠席", "遅刻", "早退"];
  const canUseLeave = leaveData.enabled !== false
    && selectedEvent?.type === "通常練習"
    && selectedEvent?.date >= new Date().toISOString().slice(0, 10)
    && leaveData.credits?.some((credit) => credit.remaining > 0 && credit.expiresOn >= selectedEvent.date);

  async function reloadTargets(force = false) {
    const data = await fetchJsonCached(token, "/api/attendance/targets", { force, errorMessage: "申請できる予定を読み込めませんでした" });
    const nextEvents = data.events || [];
    setEvents(nextEvents);
    setSelectedEventId((current) => {
      if (current && nextEvents.some((event) => String(event.id) === String(current))) return current;
      return nextEvents[0]?.id ? String(nextEvents[0].id) : "";
    });
  }

  useEffect(() => {
    let ignore = false;

    async function loadTargets() {
      setError("");
      try {
        const [, credits] = await Promise.all([
          reloadTargets(false),
          fetchJsonCached(token, "/api/leave-credits", { errorMessage: "休暇権利を読み込めませんでした" }),
        ]);
        if (!ignore) setLeaveData(credits);
      } catch (err) {
        if (!ignore) {
          setError(err.message || "申請できる予定を読み込めませんでした");
        }
      }
    }

    loadTargets();
    return () => {
      ignore = true;
    };
  }, [token]);

  useEffect(() => {
    if (!canSubmitAttendanceStatus && status === "出席") {
      setStatus("欠席");
    }
  }, [canSubmitAttendanceStatus, status]);

  async function submitAttendance() {
    if (!selectedEvent) return;
    setLoading(true);
    setMessage("");
    setError("");

    try {
      const response = await fetchApi(`${API_BASE}/api/attendance`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          eventId: selectedEvent.id,
          status,
          reason,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || "出席情報を登録できませんでした");
      }
      setMessage(data.approvalStatus === "承認済み" ? `${data.status}で登録しました。` : `${data.status}で申請しました。確認後に承認されます。`);
      invalidateCache(token, "/api/attendance");
      invalidateCache(token, "/api/events");
      invalidateCache(token, "/api/home");
      await reloadTargets(true);
    } catch (err) {
      setError(err.message || "出席情報を登録できませんでした");
    } finally {
      setLoading(false);
    }
  }

  async function submitLeaveRequest() {
    if (!selectedEvent || !canUseLeave) return;
    setLoading(true);
    setMessage("");
    setError("");
    try {
      const response = await fetchApi(`${API_BASE}/api/leave-requests`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ eventId: selectedEvent.id, reason }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "休暇権利を申請できませんでした");
      setMessage(data.message || "休暇権利の利用を申請しました。");
      ["/api/attendance", "/api/events", "/api/home", "/api/approvals", "/api/leave-credits"].forEach((path) => invalidateCache(token, path));
      const [, credits] = await Promise.all([
        reloadTargets(true),
        fetchJsonCached(token, "/api/leave-credits", { force: true }),
      ]);
      setLeaveData(credits);
    } catch (err) {
      setError(err.message || "休暇権利を申請できませんでした");
    } finally {
      setLoading(false);
    }
  }

  async function cancelAttendanceRequest() {
    const attendance = selectedEvent?.myAttendance;
    if (!attendance?.id) return;
    if (!window.confirm(`${formatDateWithWeekday(selectedEvent.date)}の${attendance.status}申請をキャンセルしますか？`)) return;
    setLoading(true);
    setMessage("");
    setError("");
    try {
      const response = await fetchApi(`${API_BASE}/api/attendance/${attendance.id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "申請をキャンセルできませんでした");
      setMessage(data.message || "出欠申請をキャンセルしました。");
      ["/api/attendance", "/api/events", "/api/home", "/api/approvals", "/api/leave-credits"].forEach((path) => invalidateCache(token, path));
      const [, credits] = await Promise.all([
        reloadTargets(true),
        fetchJsonCached(token, "/api/leave-credits", { force: true }),
      ]);
      setLeaveData(credits);
    } catch (err) {
      setError(err.message || "申請をキャンセルできませんでした");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <ScreenIntro
        eyebrow="ATTENDANCE"
        title="出欠申請"
        text="出席を選べるのは直前と直近の予定だけです。欠席・遅刻・早退は今後の予定すべてに申請できます。"
      />
      {error && <div className="card error-card">{error}</div>}
      {message && <div className="card success-card">{message}</div>}
      <Section title="申請する予定を選ぶ">
        {events.length === 0 && (
          <div className="card empty-card">
            <div className="item-title">申請できる予定はありません</div>
            <div className="item-note">直前の予定または今後の予定が登録されると、ここから回答できます。</div>
          </div>
        )}
        {events.length > 0 && (
          <>
            {events.length > 1 && (
              <select className="input" value={selectedEventId} onChange={(event) => setSelectedEventId(event.target.value)}>
                {events.map((event) => (
                  <option value={event.id} key={event.id}>
                    {formatDateWithWeekday(event.date)} {event.time} {event.title}
                  </option>
                ))}
              </select>
            )}
            <EventSummaryCard event={selectedEvent} />
            {selectedEvent?.myAttendance && (
              <div className="card success-card">
                申請済み：{selectedEvent.myAttendance.status}（{selectedEvent.myAttendance.approvalStatus}）
                {["欠席", "遅刻", "早退"].includes(selectedEvent.myAttendance.status) && selectedEvent.date >= todayKey() && (
                  <button className="small-button danger-button card-action" disabled={loading} onClick={cancelAttendanceRequest}>
                    申請をキャンセル
                  </button>
                )}
              </div>
            )}
          </>
        )}
      </Section>
      {events.length > 0 && (
        <>
          <Section title="出席状況">
            <div className="status-choice-grid">
              {statusOptions.map((item) => (
                <button
                  className={`status-choice ${status === item ? "active" : ""}`}
                  key={item}
                  onClick={() => setStatus(item)}
                >
                  <span>{item}</span>
                  {status === item && <Check size={18} />}
                </button>
              ))}
            </div>
            {selectedEvent?.isPastUnanswered && <div className="item-note">未回答の過去予定なので、後から出席・欠席・遅刻・早退を回答できます。</div>}
            {!canSubmitAttendanceStatus && <div className="item-note">この先の予定には、欠席・遅刻・早退を事前申請できます。</div>}
          </Section>
          <textarea className="input" rows={4} placeholder="理由・メモ" value={reason} onChange={(event) => setReason(event.target.value)} />
          <button className="primary-button submit-button" style={{ marginTop: 12 }} onClick={submitAttendance} disabled={loading}>
            {loading ? "送信中" : "申請を送る"}
            <Send size={18} />
          </button>
          {(leaveData.enabled !== false || currentUser?.role === "管理者") && <Section title={`休暇権利（利用可能 ${leaveData.available || 0}回）`}>
            <div className="card">
              {leaveData.enabled === false && <div className="item-title">管理者により現在停止中です</div>}
              <div className="item-note">前月のすべての練習・本番に出席すると、今月末まで使える権利が1回付与されます。欠席・遅刻・早退がある月は付与されません。</div>
              {leaveData.enabled !== false && !canUseLeave && <div className="item-note">選択した予定には利用できません。今月中の通常練習を選んでください。</div>}
              <button className="small-button" style={{ marginTop: 12 }} onClick={submitLeaveRequest} disabled={loading || !canUseLeave}>
                休暇権利を使って欠席申請
              </button>
            </div>
          </Section>}
        </>
      )}
    </>
  );
}

function AbsenceReportTable({ rows = [] }) {
  return (
    <div className="report-table-wrap">
      <table className="report-table">
        <thead><tr><th>日付</th><th>部員</th><th>パート</th><th>区分</th><th>予定</th><th>理由</th><th>承認</th><th>承認者</th></tr></thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.id}-${index}`}>
              <td>{formatDateWithWeekday(row.date)}</td>
              <td>{row.memberName}<span className="table-subtext">{row.grade}年</span></td>
              <td>{row.part}</td><td>{row.status}</td>
              <td>{row.title || row.eventType}</td>
              <td>{row.reason || "—"}</td><td>{row.approvalStatus}</td><td>{row.approvedBy || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && <div className="card empty-card">共有する欠席・遅刻・早退情報はありません。</div>}
    </div>
  );
}

function NoticesScreen({ token, onUnreadNoticesChange, currentUser }) {
  const [filter, setFilter] = useState("unread");
  const [noticeData, setNoticeData] = useState(() => getCachedData(token, "/api/announcements?filter=unread") || { announcements: [], canPublish: false, canDelete: false, targetTypes: ["全体", "パート", "学年"], parts: [] });
  const [approvalNotifications, setApprovalNotifications] = useState([]);
  const [noticeError, setNoticeError] = useState("");
  const [noticeMessage, setNoticeMessage] = useState("");
  const [targetType, setTargetType] = useState("全体");
  const [targetPart, setTargetPart] = useState("フルート");
  const [targetGrade, setTargetGrade] = useState(1);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [important, setImportant] = useState(false);
  const [sendToTeacher, setSendToTeacher] = useState(false);
  const [noticeReaders, setNoticeReaders] = useState({});
  const [openReadersId, setOpenReadersId] = useState(null);
  const [sharedReports, setSharedReports] = useState([]);
  const partOptions = useMemo(
    () => noticeData.parts?.length ? noticeData.parts : ["フルート", "クラリネット", "サックス", "トランペット", "ホルン", "トロンボーン", "ユーフォニアム", "チューバ", "打楽器"],
    [noticeData.parts],
  );
  const targetTypes = useMemo(
    () => noticeData.targetTypes?.length ? noticeData.targetTypes : ["全体", "パート", "学年"],
    [noticeData.targetTypes],
  );

  async function loadAnnouncements(nextFilter = filter) {
    setNoticeError("");
    try {
      const [data, notificationData] = await Promise.all([
        fetchJsonCached(token, `/api/announcements?filter=${nextFilter}`, { errorMessage: "お知らせを読み込めませんでした" }),
        fetchJsonCached(token, `/api/notifications?filter=${nextFilter}`, { errorMessage: "承認依頼を読み込めませんでした" }),
      ]);
      setNoticeData(data);
      setApprovalNotifications(notificationData.notifications || []);
      const unreadAnnouncements = nextFilter === "unread"
        ? (data.announcements || []).length
        : (data.announcements || []).filter((item) => !item.isRead).length;
      const unreadApprovals = nextFilter === "unread"
        ? (notificationData.notifications || []).length
        : (notificationData.notifications || []).filter((item) => !item.isRead).length;
      onUnreadNoticesChange?.(unreadAnnouncements + unreadApprovals);
    } catch (err) {
      setNoticeError(err.message || "お知らせを読み込めませんでした");
    }
  }

  useEffect(() => {
    loadAnnouncements(filter);
  }, [filter, token]);

  function loadSharedReports() {
    fetchApi(`${API_BASE}/api/absence-report/shares`, { headers: { Authorization: `Bearer ${token}` } })
      .then((response) => response.ok ? response.json() : { items: [] })
      .then((data) => setSharedReports(data.items || []))
      .catch(() => setSharedReports([]));
  }

  useEffect(() => {
    loadSharedReports();
  }, [token]);

  async function deleteSharedReport(id) {
    if (!window.confirm("この共有済みリストを削除しますか？共有相手からも見えなくなります。")) return;
    setNoticeError("");
    const response = await fetchApi(`${API_BASE}/api/admin/absence-report/shares/${id}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      setNoticeError(data.detail || "共有済みリストを削除できませんでした");
      return;
    }
    setNoticeMessage("共有済みリストを削除しました。");
    loadSharedReports();
  }

  useEffect(() => {
    if (!targetTypes.includes(targetType)) {
      setTargetType(targetTypes[0] || "全体");
    }
  }, [targetTypes, targetType]);

  async function markRead(id) {
    setNoticeError("");
    try {
      const response = await fetchApi(`${API_BASE}/api/announcements/${id}/read`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        throw new Error("既読にできませんでした");
      }
      setNoticeMessage("既読にしました。");
      invalidateCache(token, "/api/announcements");
      invalidateCache(token, "/api/home");
      loadAnnouncements(filter);
    } catch (err) {
      setNoticeError(err.message || "既読にできませんでした");
    }
  }

  async function markApprovalNotificationRead(id) {
    setNoticeError("");
    try {
      const response = await fetchApi(`${API_BASE}/api/notifications/${id}/read`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) throw new Error("確認済みにできませんでした");
      setNoticeMessage("承認依頼を確認済みにしました。");
      invalidateCache(token, "/api/notifications");
      invalidateCache(token, "/api/home");
      loadAnnouncements(filter);
    } catch (err) {
      setNoticeError(err.message || "確認済みにできませんでした");
    }
  }

  async function deleteNotice(id) {
    setNoticeError("");
    try {
      const response = await fetchApi(`${API_BASE}/api/announcements/${id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        throw new Error("削除できませんでした");
      }
      setNoticeMessage("お知らせを削除しました。");
      invalidateCache(token, "/api/announcements");
      invalidateCache(token, "/api/home");
      loadAnnouncements(filter);
    } catch (err) {
      setNoticeError(err.message || "削除できませんでした");
    }
  }

  async function publishNotice() {
    setNoticeError("");
    setNoticeMessage("");
    try {
      const response = await fetchApi(`${API_BASE}/api/announcements`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          targetType,
          targetPart: targetType === "パート" ? targetPart : null,
          targetGrade: targetType === "学年" ? Number(targetGrade) : null,
          title,
          message: body,
          isImportant: important,
          sendToTeacher: currentUser?.role === "顧問" ? false : sendToTeacher,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || "送信できませんでした");
      }
      setTitle("");
      setBody("");
      setImportant(false);
      setSendToTeacher(false);
      setNoticeMessage(`${data.targetCount}人にお知らせを送信しました。`);
      invalidateCache(token, "/api/announcements");
      invalidateCache(token, "/api/home");
      loadAnnouncements(filter);
    } catch (err) {
      setNoticeError(err.message || "送信できませんでした");
    }
  }

  async function toggleReaders(noticeId) {
    if (openReadersId === noticeId) {
      setOpenReadersId(null);
      return;
    }
    setOpenReadersId(noticeId);
    if (noticeReaders[noticeId]) return;
    try {
      const response = await fetchApi(`${API_BASE}/api/announcements/${noticeId}/reads`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "既読者を確認できませんでした");
      setNoticeReaders((current) => ({ ...current, [noticeId]: data.readers || [] }));
    } catch (err) {
      setNoticeError(err.message || "既読者を確認できませんでした");
    }
  }

  return (
    <>
      <ScreenIntro
        eyebrow="NOTICE"
        title="お知らせ"
        text={currentUser?.role === "顧問" ? "部員へお知らせを送信し、先生宛てに指定された連絡だけを確認できます。" : "重要な連絡と未読だけを先に確認できます。"}
      />
      {noticeError && <div className="card error-card">{noticeError}</div>}
      {noticeMessage && <div className="card success-card">{noticeMessage}</div>}
      {sharedReports.length > 0 && (
        <Section title="共有された欠席・遅刻情報">
          <div className="list">
            {sharedReports.map((report) => (
              <details className="card" key={report.id} open={sharedReports.length === 1}>
                <summary className="item-title">{report.part || "全部員・全パート"}｜{formatDateWithWeekday(report.createdAt)}</summary>
                <div className="item-note card-action">共有者：{report.createdBy} / 対象役職：{report.targetRoles.map(memberRoleLabel).join("・")}</div>
                {(report.startDate || report.endDate) && <div className="item-note">対象期間：{formatDateWithWeekday(report.startDate)}{report.endDate && report.endDate !== report.startDate ? ` 〜 ${formatDateWithWeekday(report.endDate)}` : ""}</div>}
                <AbsenceReportTable rows={report.rows} />
                {report.canDelete && <button className="small-button danger-button card-action" onClick={() => deleteSharedReport(report.id)}>この共有リストを削除</button>}
              </details>
            ))}
          </div>
        </Section>
      )}
      {noticeData.canPublish && (
        <Section title="お知らせを書く">
          <div className="form-stack">
            <div className="pill-row">
              {targetTypes.map((item) => (
                <button className={`pill ${targetType === item ? "active" : ""}`} key={item} onClick={() => setTargetType(item)}>
                  {item}
                </button>
              ))}
            </div>
            {targetType === "パート" && (
              <select className="input" value={targetPart} onChange={(event) => setTargetPart(event.target.value)}>
                {partOptions.map((part) => <option key={part}>{part}</option>)}
              </select>
            )}
            {targetType === "学年" && (
              <select className="input" value={targetGrade} onChange={(event) => setTargetGrade(event.target.value)}>
                {[1, 2, 3, 4].map((grade) => <option value={grade} key={grade}>{grade}年</option>)}
              </select>
            )}
            <input className="input" placeholder="タイトル" value={title} onChange={(event) => setTitle(event.target.value)} />
            <textarea className="input" rows={3} placeholder="本文" value={body} onChange={(event) => setBody(event.target.value)} />
            <label className="check-line">
              <input type="checkbox" checked={important} onChange={(event) => setImportant(event.target.checked)} />
              重要なお知らせにする
            </label>
            {currentUser?.role !== "顧問" && <label className="check-line teacher-notice-check">
              <input type="checkbox" checked={sendToTeacher} onChange={(event) => setSendToTeacher(event.target.checked)} />
              先生にもお知らせする
            </label>}
            <button className="primary-button" onClick={publishNotice}>送信する</button>
          </div>
        </Section>
      )}
      <Section title="お知らせ">
        <div className="pill-row">
          <button className={`pill ${filter === "unread" ? "active" : ""}`} onClick={() => setFilter("unread")}>未読</button>
          <button className={`pill ${filter === "all" ? "active" : ""}`} onClick={() => setFilter("all")}>すべて</button>
        </div>
      </Section>
      <div className="list">
        {approvalNotifications.map((notice) => (
          <div className={`card notice-card ${!notice.isRead ? "unread" : ""}`} key={`approval-${notice.id}`}>
            <span className="notice-badge important">出欠承認</span>
            {!notice.isRead && <span className="notice-badge">未読</span>}
            <div className="item-title">{notice.title}</div>
            <div className="item-note">{notice.message}</div>
            <div className="item-note card-action">出欠承認画面から承認または拒否を選べます。</div>
            {!notice.isRead && <button className="small-button card-action" onClick={() => markApprovalNotificationRead(notice.id)}>確認済みにする</button>}
          </div>
        ))}
        {noticeData.announcements.length === 0 && approvalNotifications.length === 0 && (
          <div className="card empty-card">
            <div className="item-title">表示するお知らせはありません</div>
            <div className="item-note">新しいお知らせが届くとここに表示されます。</div>
          </div>
        )}
        {noticeData.announcements.map((notice) => (
            <div className={`card notice-card ${!notice.isRead ? "unread" : ""}`} key={notice.id}>
              <span className={`notice-badge ${notice.isImportant ? "important" : ""}`}>
                {notice.isImportant ? "重要" : notice.targetLabel}
              </span>
              {!notice.isRead && <span className="notice-badge">未読</span>}
              <div className="item-title">{notice.title}</div>
              <div className="item-note">{notice.message}</div>
              <div className="item-note card-action">{notice.targetLabel}｜{notice.createdBy}</div>
              {notice.sendToTeacher && <div className="item-note">先生にも送信</div>}
              {!notice.isRead && <button className="small-button card-action" onClick={() => markRead(notice.id)}>既読にする</button>}
              {notice.createdByMe && <button className="small-button card-action" onClick={() => toggleReaders(notice.id)}>
                {openReadersId === notice.id ? "既読者を閉じる" : `既読者を見る（${notice.readCount}人）`}
              </button>}
              {notice.createdByMe && openReadersId === notice.id && <div className="notice-reader-list">
                {(noticeReaders[notice.id] || []).map((reader) => <div key={reader.id}>
                  <strong>{reader.name}</strong><span>{reader.role === "顧問" ? "先生" : `${reader.part}${reader.grade ? `・${reader.grade}年` : ""}`}</span>
                </div>)}
                {noticeReaders[notice.id] && noticeReaders[notice.id].length === 0 && <div className="item-note">まだ既読にした人はいません。</div>}
                {!noticeReaders[notice.id] && <div className="item-note">既読者を読み込んでいます。</div>}
              </div>}
              {noticeData.canDelete && <button className="small-button card-action" onClick={() => deleteNotice(notice.id)}>削除</button>}
            </div>
        ))}
      </div>
    </>
  );
}

function ContactScreen({ token }) {
  const cachedMemos = getCachedData(token, "/api/part-memos");
  const [memoData, setMemoData] = useState(cachedMemos || { part: "", availableParts: [], canWrite: false, memos: [] });
  const [selectedPart, setSelectedPart] = useState("");
  const [title, setTitle] = useState("");
  const [memo, setMemo] = useState("");
  const [contactError, setContactError] = useState("");
  const [contactMessage, setContactMessage] = useState("");

  async function loadMemos(part = selectedPart, force = false) {
    setContactError("");
    try {
      const query = part ? `?part=${encodeURIComponent(part)}` : "";
      const data = await fetchJsonCached(token, `/api/part-memos${query}`, {
        force,
        errorMessage: "パート連絡を読み込めませんでした",
      });
      setMemoData(data);
      setSelectedPart(data.part);
    } catch (err) {
      setContactError(err.message || "パート連絡を読み込めませんでした");
    }
  }

  useEffect(() => {
    loadMemos("");
  }, [token]);

  async function submitMemo() {
    setContactError("");
    setContactMessage("");
    try {
      const response = await fetchApi(`${API_BASE}/api/part-memos`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          part: selectedPart,
          title,
          memo,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || "投稿できませんでした");
      }
      setTitle("");
      setMemo("");
      setContactMessage("パート連絡を投稿しました。");
      invalidateCache(token, "/api/part-memos");
      loadMemos(data.part || selectedPart, true);
    } catch (err) {
      setContactError(err.message || "投稿できませんでした");
    }
  }

  async function deleteMemo(id) {
    setContactError("");
    setContactMessage("");
    try {
      const response = await fetchApi(`${API_BASE}/api/part-memos/${id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || "削除できませんでした");
      }
      setContactMessage("パート連絡を削除しました。");
      invalidateCache(token, "/api/part-memos");
      loadMemos(selectedPart, true);
    } catch (err) {
      setContactError(err.message || "削除できませんでした");
    }
  }

  return (
    <>
      <ScreenIntro
        eyebrow="CONTACT"
        title="連絡"
        text="パート内の短い連絡を流せます。一般部員も自分のパートへ投稿できます。"
      />
      {contactError && <div className="card error-card">{contactError}</div>}
      {contactMessage && <div className="card success-card">{contactMessage}</div>}
      {memoData.availableParts.length > 1 && (
        <Section title="パートを選ぶ">
          <select className="input" value={selectedPart} onChange={(event) => loadMemos(event.target.value)}>
            {memoData.availableParts.map((part) => <option key={part}>{part}</option>)}
          </select>
        </Section>
      )}
      {memoData.canWrite && (
        <Section title="連絡を書く">
          <div className="form-stack">
            <input className="input" placeholder="タイトル" value={title} onChange={(event) => setTitle(event.target.value)} />
            <textarea className="input" rows={3} placeholder="内容" value={memo} onChange={(event) => setMemo(event.target.value)} />
            <button className="primary-button" onClick={submitMemo}>投稿する</button>
          </div>
        </Section>
      )}
      <Section title="パート連絡">
        <div className="list">
          {memoData.memos.length === 0 && (
            <div className="card empty-card">
              <div className="item-title">連絡はありません</div>
              <div className="item-note">パート内の連絡が投稿されるとここに表示されます。</div>
            </div>
          )}
          {memoData.memos.map((item) => (
            <div className="message" key={item.id}>
              <div className="avatar">{item.createdBy?.slice(0, 1) || "部"}</div>
              <div className="bubble">
                <div className="item-title">{item.title}</div>
                <div className="item-note">{item.memo}</div>
                <div className="item-note card-action">{item.createdBy}｜{formatDateWithWeekday(item.createdAt)}</div>
                {item.canDelete && <button className="small-button card-action" onClick={() => deleteMemo(item.id)}>削除</button>}
              </div>
            </div>
          ))}
        </div>
      </Section>
    </>
  );
}

function RankingRows({ items, type, showWorstLabel = false }) {
  return <div className="list ranking-list">
    {items.map((row) => (
      <div className={`card ranking-row ${showWorstLabel && row.isWorst ? "ranking-worst" : ""}`} key={type === "part" ? row.part : row.id}>
        <div className="rank">{showWorstLabel && row.isWorst ? "最下位" : row.rank}</div>
        <div>
          <div className="item-title">{type === "part" ? row.part : row.name}</div>
          <div className="item-note">{type === "part" ? `${row.memberCount}人 / 承認済み記録 ${row.records}件` : `${row.part} / 承認済み記録 ${row.records}件`}</div>
        </div>
        <strong>{row.rate == null ? "—" : `${row.rate}%`}</strong>
      </div>
    ))}
  </div>;
}

function RankingScreen({ token }) {
  const currentMonth = new Date().toISOString().slice(0, 7);
  const [month, setMonth] = useState(currentMonth);
  const [data, setData] = useState(() => getCachedData(token, `/api/rankings?month=${currentMonth}`) || { partItems: [], individualItems: [] });

  useEffect(() => {
    fetchJsonCached(token, `/api/rankings?month=${month}`)
      .then(setData)
      .catch(() => {});
  }, [token, month]);

  const partItems = (data.partItems || []).map((item, index) => ({ ...item, rank: index + 1 }));
  const individualItems = (data.individualItems || data.items || []).map((item, index) => ({ ...item, rank: index + 1 }));
  const partPreview = partItems.slice(0, 3);
  if (partItems.length > 3) partPreview.push({ ...partItems[partItems.length - 1], isWorst: true });
  const individualPreview = individualItems.slice(0, 10);

  return (
    <>
      <ScreenIntro
        eyebrow="RANKING"
        title="ランキング"
        text="承認済みの出席記録を月単位で確認できます。"
        action={<input className="month-input" type="month" value={month} onChange={(event) => setMonth(event.target.value)} />}
      />
      <Section title="パートの部">
        <RankingRows items={partPreview} type="part" showWorstLabel />
        {partItems.length === 0 && <div className="card empty-card">ランキング対象のパートがありません。</div>}
        {partItems.length > 0 && <details className="card ranking-details">
          <summary>全パートのランキングを見る</summary>
          <RankingRows items={partItems} type="part" />
        </details>}
      </Section>
      <Section title="個人の部">
        <RankingRows items={individualPreview} type="individual" />
        {individualItems.length === 0 && <div className="card empty-card">ランキング対象の部員がいません。</div>}
        {individualItems.length > 0 && <details className="card ranking-details">
          <summary>全部員のランキングを見る</summary>
          <RankingRows items={individualItems} type="individual" />
        </details>}
      </Section>
    </>
  );
}

function publicationKindLabel(kind) {
  if (kind === "ranking") return "ランキング";
  if (kind === "member_attendance") return "部員別出席";
  if (kind === "member_event_types") return "個人・予定種別";
  if (kind === "overall_rate") return "全体出席率";
  if (kind === "answer_rate") return "回答率";
  if (kind === "attendance_breakdown") return "出欠内訳";
  if (kind === "part_rates") return "パート別";
  if (kind === "daily_rates") return "日別";
  if (kind === "event_type_rates") return "予定種別";
  if (kind === "operations_dashboard") return "運営分析";
  return "統計";
}

function publicationAudienceLabel(item) {
  if (item.audienceType === "role") return `役職：${memberRoleLabel(item.audienceValue)}`;
  if (item.audienceType === "part") return `パート：${item.audienceValue}`;
  if (item.audienceType === "member") return "指定した個人のみ";
  return "全員";
}

function PublicationCards({ items, manage = false, onToggle, onDelete }) {
  return <div className="list">
    {items.map((item) => <div className={`card publication-card ${item.isPublished ? "" : "publication-hidden"}`} key={item.id}>
      <div className="publication-head">
        <div>
          <span className="notice-badge">{publicationKindLabel(item.kind)}</span>
          <div className="item-title">{item.title}</div>
          <div className="item-note">{item.period}｜公開範囲：{publicationAudienceLabel(item)}</div>
        </div>
        {manage && <span className="notice-badge">{item.isPublished ? "公開中" : "非公開"}</span>}
      </div>
      {item.kind === "overall_rate" || item.kind === "answer_rate" ? (
        <div className="publication-single-metric"><Metric label={item.payload?.label || publicationKindLabel(item.kind)} value={item.payload?.value == null ? "—" : `${item.payload.value}${item.payload?.unit || ""}`} note={item.payload?.note || item.period} /></div>
      ) : item.kind === "attendance_breakdown" ? (
        <div className="publication-breakdown">
          <span>出席 <strong>{item.payload?.summary?.present || 0}</strong></span><span>遅刻 <strong>{item.payload?.summary?.late || 0}</strong></span><span>早退 <strong>{item.payload?.summary?.early || 0}</strong></span><span>欠席 <strong>{item.payload?.summary?.absent || 0}</strong></span><span>未回答 <strong>{item.payload?.summary?.unanswered || 0}</strong></span><span>承認待ち <strong>{item.payload?.summary?.pending || 0}</strong></span>
        </div>
      ) : ["part_rates", "daily_rates", "event_type_rates"].includes(item.kind) ? (
        <RateBars items={(item.payload?.items || []).map((row) => ({...row, label: item.kind === "daily_rates" ? formatDateWithWeekday(row.label) : row.label}))} />
      ) : item.kind === "ranking" ? (
        <div className="publication-ranking">
          {(item.payload?.items || []).slice(0, 5).map((row, index) => (
            <div key={row.id}><strong>{index + 1}</strong><span>{row.name}（{row.part}）</span><b>{row.rate}%</b></div>
          ))}
        </div>
      ) : item.kind === "member_attendance" ? (
        <div className="publication-member-attendance">
          <div className="item-title">{item.payload?.member?.name}（{item.payload?.member?.part}）</div>
          <AttendanceOverview stats={item.payload?.stats} />
        </div>
      ) : item.kind === "member_event_types" ? (
        <div className="publication-member-attendance">
          <div className="item-title">{item.payload?.member?.name}（{item.payload?.member?.part}）</div>
          <div className="admin-event-type-grid">{(item.payload?.eventTypes || []).map((row) => <div className="card" key={row.label}><strong>{row.label}</strong><span>対象 {row.scheduled} / 出席 {row.attended} / 欠席 {row.absent} / 未回答 {row.unanswered}</span></div>)}</div>
        </div>
      ) : item.kind === "operations_dashboard" ? (
        <div className="publication-stats publication-dashboard">
          <Metric label="全体出席率" value={item.payload?.summary?.rate == null ? "—" : `${item.payload.summary.rate}%`} note={`${item.payload?.summary?.eventCount || 0}件の予定`} />
          <Metric label="回答率" value={item.payload?.summary?.answerRate == null ? "—" : `${item.payload.summary.answerRate}%`} note={`未回答 ${item.payload?.summary?.unanswered || 0}件`} />
          <Metric label="承認待ち" value={`${item.payload?.summary?.pending || 0}件`} note="運営確認対象" />
          <Metric label="不当欠席" value={`${item.payload?.summary?.unjustified || 0}件`} note="承認済み" />
          <div className="publication-ranking">
            {(item.payload?.ranking || []).slice(0, 3).map((row, index) => <div key={row.id}><strong>{index + 1}</strong><span>{row.name}（{row.part}）</span><b>{row.rate == null ? "—" : `${row.rate}%`}</b></div>)}
          </div>
        </div>
      ) : (
        <div className="publication-stats">
          <Metric label="全体出席率" value={item.payload?.summary?.rate == null ? "—" : `${item.payload.summary.rate}%`} note="承認済み記録" />
          <Metric label="回答率" value={item.payload?.summary?.answerRate == null ? "—" : `${item.payload.summary.answerRate}%`} note={`未回答 ${item.payload?.summary?.unanswered || 0}件`} />
          <Metric label="欠席" value={`${item.payload?.summary?.absent || 0}回`} note={`正当 ${item.payload?.summary?.justified || 0} / 不当 ${item.payload?.summary?.unjustified || 0}`} />
        </div>
      )}
      {manage && <div className="managed-event-actions card-action">
        <button className="small-button" onClick={() => onToggle(item.id)}>{item.isPublished ? "非公開にする" : "公開する"}</button>
        <button className="small-button danger-button" onClick={() => onDelete(item.id)}>削除</button>
      </div>}
    </div>)}
  </div>;
}

function AttendanceOverview({ stats }) {
  if (!stats) return null;

  const displayRate = stats.rate == null ? "—" : `${stats.rate}%`;
  const chartRate = stats.rate == null ? 0 : Math.max(0, Math.min(stats.rate, 100));

  return (
    <div className="attendance-overview">
      <div className="card attendance-score-card">
        <div className="attendance-ring" style={{ "--attendance-rate": `${chartRate * 3.6}deg` }}>
          <div>
            <strong>{displayRate}</strong>
            <span>出席率</span>
          </div>
        </div>
        <div className="attendance-score-copy">
          <div className="item-title">{stats.period?.replace("-", "年")}月の記録</div>
          <div className="item-note">
            {stats.throughDate ? `${formatDateWithWeekday(stats.throughDate)}まで` : "今日まで"}：回答済み {stats.answered ?? (stats.scheduled - stats.unanswered)}回のうち {stats.attended}回出席
          </div>
          <div className="attendance-breakdown">
            <span className="attendance-pill attended">出席 {stats.attended}</span>
            <span className="attendance-pill absent">欠席 {stats.absent}</span>
            <span className="attendance-pill unanswered">未回答 {stats.unanswered}</span>
            {stats.pending > 0 && <span className="attendance-pill pending">承認待ち {stats.pending}</span>}
          </div>
        </div>
      </div>
      {(stats.monthly || []).length > 0 && <div className="card attendance-chart-card">
        <div className="item-title">直近6か月の出席率</div>
        <div className="attendance-chart" aria-label="直近6か月の出席率グラフ">
          {(stats.monthly || []).map((month) => {
            const value = month.rate == null ? 0 : month.rate;
            return (
              <div className="attendance-bar-column" key={month.month}>
                <span className="attendance-bar-value">{month.rate == null ? "—" : `${month.rate}%`}</span>
                <div className="attendance-bar-track">
                  <div className="attendance-bar-fill" style={{ height: `${Math.max(value, value > 0 ? 8 : 0)}%` }} />
                </div>
                <span className="attendance-bar-label">{month.label}</span>
              </div>
            );
          })}
        </div>
      </div>}
    </div>
  );
}

function DetailedAttendanceBreakdown({ stats }) {
  if (!stats) return null;
  return <div className="grid two wide-grid admin-detail-metrics">
    <Metric label="回答率" value={stats.answerRate == null ? "—" : `${stats.answerRate}%`} note={`回答 ${stats.answered || 0} / 対象 ${stats.scheduled || 0}`} />
    <Metric label="通常出席" value={`${stats.present || 0}回`} note="承認済み" />
    <Metric label="遅刻・早退" value={`${(stats.late || 0) + (stats.early || 0)}回`} note={`遅刻 ${stats.late || 0} / 早退 ${stats.early || 0}`} />
    <Metric label="欠席内訳" value={`${stats.absent || 0}回`} note={`正当 ${stats.justified || 0} / 不当 ${stats.unjustified || 0}`} />
    <Metric label="未回答" value={`${stats.unanswered || 0}件`} note="回答依頼対象" />
    <Metric label="承認待ち" value={`${stats.pending || 0}件`} note="運営確認対象" />
  </div>;
}

function RateBars({ items = [], valueKey = "rate", empty = "データがありません。" }) {
  if (!items.length) return <div className="empty-card">{empty}</div>;
  return <div className="card stats-bars">{items.map((item) => {
    const value = item[valueKey];
    return <div className="stats-bar-row" key={item.label}>
      <span>{item.label}</span><div className="stats-track"><div style={{width:`${value || 0}%`}} /></div><strong>{value == null ? "—" : `${value}%`}</strong>
    </div>;
  })}</div>;
}

function ClassLateWeekdayPicker({ value = [], onChange }) {
  function toggle(day) {
    const current = value || [];
    onChange(current.includes(day)
      ? current.filter((item) => item !== day)
      : [...current, day]);
  }

  return (
    <div className="weekday-picker">
      {weekdayOptions.map((day) => (
        <label className={`weekday-chip ${value?.includes(day) ? "active" : ""}`} key={day}>
          <input type="checkbox" checked={Boolean(value?.includes(day))} onChange={() => toggle(day)} />
          {day}
        </label>
      ))}
    </div>
  );
}

function classLateWeekdayText(days = []) {
  return days?.length ? `${days.join("・")}曜` : "なし";
}

function ProfileScreen({ currentUser, token, onUserUpdate }) {
  const [birthday, setBirthday] = useState(currentUser?.birthday || "");
  const [hometown, setHometown] = useState(currentUser?.hometown || "");
  const [bandYears, setBandYears] = useState(currentUser?.bandYears ?? "");
  const [mbti, setMbti] = useState(currentUser?.mbti || "");
  const [duty, setDuty] = useState(currentUser?.duty || "");
  const [classLateWeekdays, setClassLateWeekdays] = useState(currentUser?.classLateWeekdays || []);
  const [editingProfile, setEditingProfile] = useState(
    !(currentUser?.birthday || currentUser?.hometown || currentUser?.bandYears != null || currentUser?.mbti || currentUser?.duty || currentUser?.classLateWeekdays?.length)
  );
  const [profileError, setProfileError] = useState("");
  const [profileMessage, setProfileMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [attendanceStats, setAttendanceStats] = useState(null);
  const [leaveData, setLeaveData] = useState({ enabled: false, available: 0, credits: [] });

  useEffect(() => {
    setBirthday(currentUser?.birthday || "");
    setHometown(currentUser?.hometown || "");
    setBandYears(currentUser?.bandYears ?? "");
    setMbti(currentUser?.mbti || "");
    setDuty(currentUser?.duty || "");
    setClassLateWeekdays(currentUser?.classLateWeekdays || []);
    setEditingProfile(!(currentUser?.birthday || currentUser?.hometown || currentUser?.bandYears != null || currentUser?.mbti || currentUser?.duty || currentUser?.classLateWeekdays?.length));
  }, [currentUser]);

  useEffect(() => {
    if (!token) return;
    let ignore = false;

    Promise.all([
      fetchJsonCached(token, "/api/attendance/stats", { errorMessage: "出席データを読み込めませんでした" }),
      fetchJsonCached(token, "/api/leave-credits", { errorMessage: "休暇権利を読み込めませんでした" }),
    ])
      .then(([stats, credits]) => {
        if (!ignore) {
          setAttendanceStats(stats);
          setLeaveData(credits);
        }
      })
      .catch(() => {
        if (!ignore) {
          setAttendanceStats(null);
          setLeaveData({ enabled: false, available: 0, credits: [] });
        }
      });

    return () => {
      ignore = true;
    };
  }, [token]);

  async function saveProfile() {
    setProfileError("");
    setProfileMessage("");
    setSaving(true);
    try {
      const response = await fetchApi(`${API_BASE}/api/profile`, {
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          birthday: birthday || null,
          hometown: hometown || null,
          bandYears: bandYears === "" ? null : Number(bandYears),
          mbti: mbti || null,
          duty: duty || null,
          classLateWeekdays,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || "保存できませんでした");
      }
      onUserUpdate(data.user);
      setProfileMessage("プロフィールを保存しました。");
      setEditingProfile(false);
    } catch (err) {
      setProfileError(err.message || "保存できませんでした");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <ScreenIntro
        eyebrow="PROFILE"
        title="マイページ"
        text={leaveData.enabled !== false || currentUser?.role === "管理者" ? "自分の基本情報、休暇権利、プロフィール情報を確認できます。" : "自分の基本情報とプロフィール情報を確認できます。"}
      />
      {profileError && <div className="card error-card">{profileError}</div>}
      {profileMessage && <div className="card success-card">{profileMessage}</div>}
      <Section title="マイページ">
        <div className="card profile-head">
          <div className="profile-avatar">{currentUser?.name?.slice(0, 1) || "B"}</div>
          <div>
            <div className="item-title">{currentUser?.name}</div>
            <div className="item-note">{currentUser?.part} / {currentUser?.grade}年 / {currentUser?.roleLabel || currentUser?.role}</div>
            <div className="item-note">誕生日：{currentUser?.birthday ? formatDateWithWeekday(currentUser.birthday) : "未登録"}｜出身：{currentUser?.hometown || "未登録"}</div>
            <div className="item-note">吹奏楽年数：{currentUser?.bandYears ?? "未登録"}年｜MBTI：{currentUser?.mbti || "未登録"}</div>
            <div className="item-note">係：{currentUser?.duty || "なし"}</div>
            <div className="item-note">授業遅刻になる曜日：{classLateWeekdayText(currentUser?.classLateWeekdays)}</div>
          </div>
        </div>
      </Section>
      <Section title="出席状況">
        <AttendanceOverview stats={attendanceStats} />
      </Section>
      {(leaveData.enabled !== false || currentUser?.role === "管理者") && <Section title={`休暇権利：利用可能 ${leaveData.available || 0}回`}>
        <div className="list">
          {leaveData.enabled === false && <div className="card error-card">休暇権利機能は管理者により停止されています。</div>}
          {leaveData.credits?.map((credit) => (
            <div className="card approval-row" key={credit.grantMonth}>
              <div>
                <div className="item-title">{credit.grantMonth} 付与分</div>
                <div className="item-note">{credit.eligibleMonth}の皆勤で付与 / 有効期限：{formatDateWithWeekday(credit.expiresOn)}</div>
              </div>
              <span className="notice-badge">残り {credit.remaining}回</span>
            </div>
          ))}
          {!leaveData.credits?.length && <div className="card empty-card">付与された休暇権利はまだありません。</div>}
        </div>
      </Section>}
      <div className="grid two wide-grid">
        <Metric label="今月の予定" value={attendanceStats ? `${attendanceStats.scheduled}回` : "—"} note="出席対象" />
        <Metric label="承認待ち" value={attendanceStats ? `${attendanceStats.pending}件` : "—"} note="出席・欠席申請" />
      </div>
      <Section
        title="プロフィール編集"
        action={!editingProfile && <button className="small-button" onClick={() => setEditingProfile(true)}>編集</button>}
      >
        {editingProfile ? (
          <div className="form-stack">
            <label className="field-label">
              誕生日
              <input className="input" type="date" value={birthday} onChange={(event) => setBirthday(event.target.value)} />
              {birthday && <span className="item-note">{formatDateWithWeekday(birthday)}</span>}
            </label>
            <label className="field-label">
              出身
              <input className="input" placeholder="例：大阪府" value={hometown} onChange={(event) => setHometown(event.target.value)} />
            </label>
            <label className="field-label">
              吹奏楽年数
              <input className="input" type="number" min="0" value={bandYears} onChange={(event) => setBandYears(event.target.value)} />
            </label>
            <label className="field-label">
              MBTI
              <input className="input" placeholder="例：ENFP" value={mbti} onChange={(event) => setMbti(event.target.value.toUpperCase())} />
            </label>
            <label className="field-label">
              係（任意）
              <input className="input" placeholder="例：楽譜係" value={duty} onChange={(event) => setDuty(event.target.value)} />
            </label>
            <label className="field-label">
              授業遅刻になる曜日
              <ClassLateWeekdayPicker value={classLateWeekdays} onChange={setClassLateWeekdays} />
            </label>
            <button className="primary-button" onClick={saveProfile} disabled={saving}>{saving ? "保存中" : "保存"}</button>
          </div>
        ) : (
          <div className="card empty-card">プロフィールは保存済みです。変更するときは右上の「編集」を押してください。</div>
        )}
      </Section>
    </>
  );
}

function ScopedMemberAttendance({ token, title }) {
  const currentMonth = new Date().toISOString().slice(0, 7);
  const [month, setMonth] = useState(currentMonth);
  const [data, setData] = useState(null);
  const [selectedMemberId, setSelectedMemberId] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let ignore = false;
    setError("");
    fetchApi(`${API_BASE}/api/operations/member-attendance?month=${encodeURIComponent(month)}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.detail || "出席情報を読み込めませんでした");
        if (ignore) return;
        setData(body);
        setSelectedMemberId((current) => (
          (body.items || []).some((item) => String(item.id) === String(current))
            ? current
            : String(body.items?.[0]?.id || "")
        ));
      })
      .catch((err) => { if (!ignore) setError(err.message || "出席情報を読み込めませんでした"); });
    return () => { ignore = true; };
  }, [token, month]);

  const members = data?.items || [];
  const selectedMember = members.find((item) => String(item.id) === String(selectedMemberId));
  return <Section title={title} action={data?.scope && <span className="notice-badge">{data.scope}</span>}>
    <div className="card scoped-attendance-panel">
      <div className="scoped-attendance-controls">
        <label className="field-label">対象月<input className="input" type="month" value={month} onChange={(event) => setMonth(event.target.value)} /></label>
        <label className="field-label">部員<select className="input" value={selectedMemberId} onChange={(event) => setSelectedMemberId(event.target.value)}>
          {members.map((item) => <option value={item.id} key={item.id}>{item.name}（{item.part}・{item.grade}年）</option>)}
        </select></label>
      </div>
      {error && <div className="error-card">{error}</div>}
      {!data && !error && <div className="empty-card">出席情報を読み込んでいます。</div>}
      {data && members.length === 0 && <div className="empty-card">対象の部員はいません。</div>}
      {selectedMember && <div className="scoped-attendance-detail">
        <div className="scoped-member-heading"><div><strong>{selectedMember.name}</strong><span>{selectedMember.part}・{selectedMember.grade}年・{memberRoleLabel(selectedMember.role)}</span></div><span>{month.replace("-", "年")}月</span></div>
        <AttendanceOverview stats={selectedMember.stats} compact />
        <div className="scoped-attendance-counts">
          <span className="attendance-pill attended">出席 {selectedMember.stats.present || 0}</span>
          <span className="attendance-pill pending">遅刻 {selectedMember.stats.late || 0}</span>
          <span className="attendance-pill pending">早退 {selectedMember.stats.early || 0}</span>
          <span className="attendance-pill absent">欠席 {selectedMember.stats.absent || 0}</span>
          <span className="attendance-pill">未回答 {selectedMember.stats.unanswered || 0}</span>
          <span className="attendance-pill pending">承認待ち {selectedMember.stats.pending || 0}</span>
        </div>
        <details className="scoped-attendance-history">
          <summary>予定ごとの出席履歴を見る</summary>
          <div className="scoped-attendance-rows">
            {(selectedMember.details || []).map((detail) => <div key={detail.eventId}>
              <span><strong>{formatDateWithWeekday(detail.date)}</strong><small>{detail.title} / {detail.eventType}</small></span>
              <span className={`notice-badge attendance-status-${detail.status}`}>{detail.status}</span>
              <span>{detail.approvalStatus}</span>
              <span>{detail.reason || "理由なし"}{detail.absenceType !== "なし" ? `（${detail.absenceType}）` : ""}</span>
            </div>)}
            {!selectedMember.details?.length && <div className="item-note">この月の予定はありません。</div>}
          </div>
        </details>
      </div>}
    </div>
  </Section>;
}

function ApprovalsScreen({ token, setActive, currentUser }) {
  const cachedApprovals = getCachedData(token, "/api/approvals");
  const [items, setItems] = useState(cachedApprovals?.items || []);
  const [approvedItems, setApprovedItems] = useState(cachedApprovals?.approvedItems || []);
  const [error, setError] = useState("");
  const [decisions, setDecisions] = useState({});

  async function load() {
    const data = await fetchJsonCached(token, "/api/approvals", { errorMessage: "承認待ちを読み込めませんでした" }).catch((err) => {
      setError(err.message || "承認待ちを読み込めませんでした");
      return null;
    });
    if (!data) return;
    setItems(data.items || []);
    setApprovedItems(data.approvedItems || []);
  }
  useEffect(() => { if (token) load(); }, [token]);

  async function approve(item) {
    const absenceType = item.status === "出席" ? "なし" : item.absenceType === "休暇申請" ? "正当" : decisions[item.id] || "正当";
    const response = await fetchApi(`${API_BASE}/api/approvals/${item.id}/approve`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ absenceType }),
    });
    if (!response.ok) return setError("承認できませんでした");
    invalidateCache(token, "/api/approvals");
    invalidateCache(token, "/api/home");
    invalidateCache(token, "/api/events");
    invalidateCache(token, "/api/leave-credits");
    load();
  }

  async function reject(item) {
    if (!window.confirm(`${item.memberName}さんの${item.status}申請を拒否しますか？`)) return;
    const response = await fetchApi(`${API_BASE}/api/approvals/${item.id}/reject`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) return setError(body.detail || "申請を拒否できませんでした");
    setError("");
    invalidateCache(token, "/api/approvals");
    invalidateCache(token, "/api/home");
    invalidateCache(token, "/api/events");
    invalidateCache(token, "/api/leave-credits");
    load();
  }

  async function cancelAttendance(item) {
    if (!window.confirm(`${item.memberName}さんの出席申請を拒否して、出席扱いを取り消しますか？`)) return;
    const response = await fetchApi(`${API_BASE}/api/approvals/${item.id}/attendance`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) return setError("出席申請を拒否できませんでした");
    setError("");
    invalidateCache(token, "/api/approvals");
    invalidateCache(token, "/api/home");
    invalidateCache(token, "/api/events");
    load();
  }

  return <>
    <ScreenIntro eyebrow="APPROVALS" title="出欠申請の承認" text="役職に応じて担当する部員の欠席・遅刻・早退申請を確認します。" />
    {error && <div className="card error-card">{error}</div>}
    <Section title="承認担当ルール">
      <div className="card approval-rule-card">
        <div><strong>パートリーダー</strong><span>自分のパートの一般部員を承認</span></div>
        <div><strong>部長・副部長</strong><span>パートリーダーを承認</span></div>
        <div><strong>部長と副部長</strong><span>お互いの申請を承認</span></div>
        <div><strong>管理者</strong><span>トラブル対応のため全申請を確認可能</span></div>
      </div>
    </Section>
    <Section title={`未承認 ${items.length}件`}>
      <div className="list">
        {items.map((item) => <div className="card approval-row" key={item.id}>
          <div><div className="item-title">{formatDateWithWeekday(item.date)}｜{item.memberName}｜{item.status}</div>
          <div className="item-note">{item.part} / {item.eventType} / {item.title}</div>
          {item.reason && <div className="item-note">理由：{item.reason}</div>}</div>
          <div className="approval-actions">
            {item.absenceType === "休暇申請" && <span className="notice-badge">休暇権利申請</span>}
            {item.status !== "出席" && item.absenceType !== "休暇申請" && <select className="input" value={decisions[item.id] || "正当"} onChange={(event) => setDecisions({...decisions, [item.id]:event.target.value})}>
              <option value="正当">正当</option><option value="不当">不当</option>
            </select>}
            <button className="primary-button" onClick={() => approve(item)}>{item.absenceType === "休暇申請" ? "休暇申請を承認" : "承認"}</button>
            <button className="small-button danger-button" onClick={() => reject(item)}>拒否</button>
          </div>
        </div>)}
        {items.length === 0 && <div className="card empty-card">未承認の申請はありません。</div>}
      </div>
    </Section>
    <Section title={`処理済み履歴 ${approvedItems.length}件`}>
      <div className="list">
        {approvedItems.map((item) => (
          <div className="card approval-row" key={`approved-${item.id}`}>
            <div>
              <div className="item-title">{formatDateWithWeekday(item.date)}｜{item.memberName}｜{item.status}</div>
              <div className="item-note">{item.part} / {item.eventType} / {item.title}</div>
              {item.reason && <div className="item-note">理由：{item.reason}</div>}
              <div className="item-note">判定：{item.absenceType || "なし"} / 処理者：{item.approvedBy || "—"} / {item.approvedAt ? formatDateWithWeekday(item.approvedAt) : "処理日時なし"}</div>
            </div>
            <div className="approval-actions">
              {["出席", "遅刻", "欠席", "早退"].includes(item.status) && (
                <span className={`notice-badge attendance-status-${item.status}`}>{item.status}</span>
              )}
              <span className={`notice-badge ${item.approvalStatus === "拒否" ? "important" : ""}`}>{item.approvalStatus}</span>
              {item.status === "出席" && item.approvalStatus === "承認済み" && <button className="small-button danger-button" onClick={() => cancelAttendance(item)}>申請拒否</button>}
            </div>
          </div>
        ))}
        {approvedItems.length === 0 && <div className="card empty-card">処理済みの申請履歴はありません。</div>}
      </div>
    </Section>
    {currentUser?.role === "パートリーダー" && <ScopedMemberAttendance token={token} title="自分のパートの出席管理" />}
    <button className="ghost-button" onClick={() => setActive("ops")}>運営に戻る</button>
  </>;
}

function memberRoleLabel(role) {
  return role === "顧問" ? "先生" : role;
}

function memberRoleClass(role) {
  const roleClasses = {
    "部長": "role-president",
    "副部長": "role-vice",
    "パートリーダー": "role-leader",
    "顧問": "role-advisor",
  };
  return `notice-badge role-badge ${roleClasses[role] || "role-member"}`;
}

function memberAffiliationLabel(member, canViewFull = false) {
  const role = member?.role;
  if (role === "顧問") {
    return canViewFull && member.student_id ? `${member.student_id} / 先生` : "先生";
  }
  return `${canViewFull && member.student_id ? `${member.student_id} / ` : ""}${member.part || "パート未登録"}`;
}

function MembersScreen({ token, setActive }) {
  const empty = { studentId: "", name: "", grade: 1, birthday: "", part: "フルート", role: "一般部員", status: "在籍", hometown: "", bandYears: "", mbti: "", duty: "", classLateWeekdays: [] };
  const [data, setData] = useState(() => getCachedData(token, "/api/members") || { members: [], parts: [], roles: [], canManage: false, canViewFull: false });
  const [form, setForm] = useState(empty);
  const [editForm, setEditForm] = useState(empty);
  const [editingMemberId, setEditingMemberId] = useState(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [selectedMemberId, setSelectedMemberId] = useState(null);
  const [registrationRequests, setRegistrationRequests] = useState([]);
  const [reviewNotes, setReviewNotes] = useState({});
  const [registrationAssignments, setRegistrationAssignments] = useState({});
  const isTeacherForm = form.role === "顧問";
  const isEditingTeacher = editForm.role === "顧問";

  async function load() {
    const body = await fetchJsonCached(token, "/api/members", { errorMessage: "部員を読み込めませんでした" }).catch((err) => {
      setError(err.message || "部員を読み込めませんでした");
      return null;
    });
    if (!body) return;
    setData(body);
    if (body.canManage) loadRegistrationRequests();
  }

  async function loadRegistrationRequests() {
    const response = await fetchApi(`${API_BASE}/api/member-registration-requests`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) return setError(body.detail || "登録申請を読み込めませんでした");
    setRegistrationRequests(body.items || []);
  }

  async function reviewRegistration(requestId, action) {
    const assignment = registrationAssignments[requestId] || { grade: 1, part: partOptions[0] };
    const response = await fetchApi(`${API_BASE}/api/member-registration-requests/${requestId}/${action}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ note: reviewNotes[requestId] || "", ...assignment }),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) return setError(body.detail || "登録申請を処理できませんでした");
    invalidateCache(token, "/api/members");
    setError("");
    setMessage(action === "approve" ? "登録申請を承認し、部員に追加しました。" : "登録申請を拒否しました。");
    load();
  }
  useEffect(() => { if (token) load(); }, [token]);

  async function add(event) {
    event.preventDefault();
    const response = await fetchApi(`${API_BASE}/api/members`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        ...form,
        bandYears: form.bandYears === "" ? null : Number(form.bandYears),
        mbti: form.mbti || null,
      }),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) return setError(body.detail || "部員を追加できませんでした");
    invalidateCache(token, "/api/members");
    invalidateCache(token, "/api/operations");
    setForm(empty); setError(""); setMessage("部員を追加しました。初回は学籍番号と暗証番号0でログインし、本人が新しい4桁の暗証番号を設定します。"); load();
  }

  function memberToForm(member) {
    return {
      studentId: member.student_id || "",
      name: member.name || "",
      grade: member.grade ?? 1,
      birthday: member.birthday || "",
      part: member.part || "フルート",
      role: member.role || "一般部員",
      status: member.status || "在籍",
      email: member.email || "",
      phone: member.phone || "",
      hometown: member.hometown || "",
      bandYears: member.band_years ?? "",
      mbti: member.mbti || "",
      duty: member.duty || "",
      classLateWeekdays: member.classLateWeekdays || [],
      joinDate: member.join_date || "",
      leaveDate: member.leave_date || "",
    };
  }

  function startEdit(member) {
    setEditingMemberId(member.id);
    setEditForm(memberToForm(member));
    setError("");
    setMessage("");
  }

  async function saveEdit(event) {
    event.preventDefault();
    if (!editingMemberId) return;
    const response = await fetchApi(`${API_BASE}/api/members/${editingMemberId}`, {
      method: "PATCH",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        ...editForm,
        bandYears: editForm.bandYears === "" ? null : Number(editForm.bandYears),
        mbti: editForm.mbti || null,
      }),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) return setError(body.detail || "部員情報を更新できませんでした");
    invalidateCache(token, "/api/members");
    invalidateCache(token, "/api/operations");
    invalidateCache(token, "/api/approvals");
    setEditingMemberId(null);
    setEditForm(empty);
    setError("");
    setMessage("部員情報を更新しました。");
    load();
  }

  async function removeMember(member) {
    if (!window.confirm(`${member.name}さんを部員一覧から完全に削除しますか？\n出欠記録や休暇権利など、この部員に紐づくデータも削除されます。`)) return;
    const response = await fetchApi(`${API_BASE}/api/members/${member.id}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) return setError(body.detail || "部員を削除できませんでした");
    invalidateCache(token);
    setEditingMemberId((current) => current === member.id ? null : current);
    setSelectedMemberId((current) => current === member.id ? null : current);
    setError("");
    setMessage(`${member.name}さんを削除しました。`);
    load();
  }

  async function resetMemberPin(member) {
    if (!window.confirm(`${member.name}さんの暗証番号をリセットしますか？\n次回は学籍番号と初期暗証番号0でログインし、本人が新しい4桁の暗証番号を設定します。`)) return;
    const response = await fetchApi(`${API_BASE}/api/admin/members/${member.id}/reset-pin`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) return setError(body.detail || "暗証番号をリセットできませんでした");
    invalidateCache(token, "/api/members");
    setError("");
    setMessage(body.message || "暗証番号をリセットしました。");
    load();
  }

  return <>
    <ScreenIntro eyebrow="MEMBERS" title={data.canManage ? "部員管理" : "部員一覧"} text={data.canViewFull ? "部員の登録情報を確認できます。" : "部員の公開プロフィールを確認できます。"} />
    {error && <div className="card error-card">{error}</div>}
    {message && <div className="card success-card">{message}</div>}
    {data.canManage && <>
      <Section title={`登録申請 ${registrationRequests.filter((item) => item.status === "申請中").length}件`}>
        <div className="list">
          {registrationRequests.filter((item) => item.status === "申請中").map((item) => <div className="card registration-request" key={item.id}>
            <div>
              <div className="item-title">{item.name}（{item.studentId}）</div>
              <div className="item-note">申請日：{formatDateWithWeekday(item.createdAt)}</div>
            </div>
            <div className="registration-assignment">
              <label className="field-label">学年<input className="input" type="number" min="1" max="6" value={(registrationAssignments[item.id] || {grade:1}).grade} onChange={(event) => setRegistrationAssignments({...registrationAssignments, [item.id]: {...(registrationAssignments[item.id] || {part:partOptions[0]}), grade:Number(event.target.value)}})} /></label>
              <label className="field-label">パート<select className="input" value={(registrationAssignments[item.id] || {part:partOptions[0]}).part} onChange={(event) => setRegistrationAssignments({...registrationAssignments, [item.id]: {...(registrationAssignments[item.id] || {grade:1}), part:event.target.value}})}>{partOptions.map((part) => <option key={part}>{part}</option>)}</select></label>
            </div>
            <input className="input" placeholder="管理メモ（任意）" value={reviewNotes[item.id] || ""} onChange={(event) => setReviewNotes({...reviewNotes, [item.id]: event.target.value})} />
            <div className="registration-actions">
              <button className="small-button" onClick={() => reviewRegistration(item.id, "approve")}>承認して追加</button>
              <button className="small-button danger-button" onClick={() => reviewRegistration(item.id, "reject")}>拒否</button>
            </div>
          </div>)}
          {registrationRequests.filter((item) => item.status === "申請中").length === 0 && <div className="card empty-card">承認待ちの登録申請はありません。</div>}
        </div>
        {registrationRequests.some((item) => item.status !== "申請中") && <details className="card registration-history">
          <summary>処理済みの申請を見る</summary>
          {registrationRequests.filter((item) => item.status !== "申請中").map((item) => <div className="list-item" key={item.id}>
            <div><div className="item-title">{item.name}（{item.studentId}）</div><div className="item-note">{item.part} / {item.status} / {item.reviewNote || "メモなし"}</div></div>
          </div>)}
        </details>}
      </Section>
      <Section title="部員追加"><form className="card member-form" onSubmit={add}>
        <label className="field-label">学籍番号<input className="input" required placeholder="例：2026001" value={form.studentId} onChange={(e) => setForm({...form, studentId:e.target.value})} /></label>
        <label className="field-label">名前<input className="input" required placeholder="氏名" value={form.name} onChange={(e) => setForm({...form, name:e.target.value})} /></label>
        <label className="field-label">役職<select className="input" value={form.role} onChange={(e) => setForm({...form, role:e.target.value})}>{data.roles.map((role) => <option key={role} value={role}>{memberRoleLabel(role)}</option>)}</select></label>
        {!isTeacherForm && <>
          <label className="field-label">学年<input className="input" type="number" min="0" max="6" value={form.grade} onChange={(e) => setForm({...form, grade:Number(e.target.value)})} /></label>
          <label className="field-label">パート<select className="input" value={form.part} onChange={(e) => setForm({...form, part:e.target.value})}>{data.parts.map((part) => <option key={part}>{part}</option>)}</select></label>
          <label className="field-label">誕生日<input className="input" type="date" value={form.birthday} onChange={(e) => setForm({...form, birthday:e.target.value})} />{form.birthday && <span className="item-note">{formatDateWithWeekday(form.birthday)}</span>}</label>
          <label className="field-label">出身<input className="input" placeholder="例：大阪府" value={form.hometown} onChange={(e) => setForm({...form, hometown:e.target.value})} /></label>
          <label className="field-label">吹奏楽年数<input className="input" type="number" min="0" value={form.bandYears} onChange={(e) => setForm({...form, bandYears:e.target.value})} /></label>
          <label className="field-label">MBTI<input className="input" placeholder="例：ENFP" value={form.mbti} onChange={(e) => setForm({...form, mbti:e.target.value.toUpperCase()})} /></label>
          <label className="field-label">係（任意）<input className="input" placeholder="例：楽譜係" value={form.duty} onChange={(e) => setForm({...form, duty:e.target.value})} /></label>
          <label className="field-label member-form-wide">授業遅刻になる曜日<ClassLateWeekdayPicker value={form.classLateWeekdays} onChange={(days) => setForm({...form, classLateWeekdays: days})} /></label>
        </>}
        {isTeacherForm && <div className="item-note teacher-form-note">先生は番号と名前だけで登録できます。</div>}
        <button className="primary-button member-submit">この部員を追加</button>
      </form></Section>
      {editingMemberId && <Section title="部員情報編集"><form className="card member-form" onSubmit={saveEdit}>
        <label className="field-label">学籍番号<input className="input" required value={editForm.studentId} onChange={(e) => setEditForm({...editForm, studentId:e.target.value})} /></label>
        <label className="field-label">名前<input className="input" required value={editForm.name} onChange={(e) => setEditForm({...editForm, name:e.target.value})} /></label>
        <label className="field-label">役職<select className="input" value={editForm.role} onChange={(e) => setEditForm({
          ...editForm,
          role: e.target.value,
          part: e.target.value === "顧問" ? editForm.part : (data.parts.includes(editForm.part) ? editForm.part : data.parts[0] || "フルート"),
          grade: e.target.value === "顧問" ? editForm.grade : (editForm.grade || 1),
        })}>{data.roles.map((role) => <option key={role} value={role}>{memberRoleLabel(role)}</option>)}</select></label>
        {!isEditingTeacher && <>
          <label className="field-label">学年<input className="input" type="number" min="0" max="6" value={editForm.grade} onChange={(e) => setEditForm({...editForm, grade:Number(e.target.value)})} /></label>
          <label className="field-label">パート<select className="input" value={editForm.part} onChange={(e) => setEditForm({...editForm, part:e.target.value})}>{data.parts.map((part) => <option key={part}>{part}</option>)}</select></label>
          <label className="field-label">誕生日<input className="input" type="date" value={editForm.birthday} onChange={(e) => setEditForm({...editForm, birthday:e.target.value})} />{editForm.birthday && <span className="item-note">{formatDateWithWeekday(editForm.birthday)}</span>}</label>
          <label className="field-label">出身<input className="input" value={editForm.hometown} onChange={(e) => setEditForm({...editForm, hometown:e.target.value})} /></label>
          <label className="field-label">吹奏楽年数<input className="input" type="number" min="0" value={editForm.bandYears} onChange={(e) => setEditForm({...editForm, bandYears:e.target.value})} /></label>
          <label className="field-label">MBTI<input className="input" value={editForm.mbti} onChange={(e) => setEditForm({...editForm, mbti:e.target.value.toUpperCase()})} /></label>
          <label className="field-label">係（任意）<input className="input" value={editForm.duty} onChange={(e) => setEditForm({...editForm, duty:e.target.value})} /></label>
          <label className="field-label member-form-wide">授業遅刻になる曜日<ClassLateWeekdayPicker value={editForm.classLateWeekdays} onChange={(days) => setEditForm({...editForm, classLateWeekdays: days})} /></label>
          <label className="field-label">電話<input className="input" value={editForm.phone} onChange={(e) => setEditForm({...editForm, phone:e.target.value})} /></label>
          <label className="field-label">メール<input className="input" type="email" value={editForm.email} onChange={(e) => setEditForm({...editForm, email:e.target.value})} /></label>
        </>}
        {isEditingTeacher && <div className="item-note teacher-form-note">先生は番号と名前だけで登録・編集できます。</div>}
        <button className="primary-button member-submit">保存する</button>
        <button type="button" className="ghost-button member-submit" onClick={() => { setEditingMemberId(null); setEditForm(empty); }}>キャンセル</button>
      </form></Section>}
    </>}
    <Section title={`部員一覧 ${data.members.length}人`}><div className="member-table">
      {data.members.map((member) => {
        const selected = selectedMemberId === member.id;
        return <div role="button" tabIndex={0} aria-expanded={selected} className={`card member-row member-card-button ${selected ? "selected" : ""}`} key={member.id} onClick={() => setSelectedMemberId(selected ? null : member.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") setSelectedMemberId(selected ? null : member.id); }}>
          <div>
            <div className="item-title">{member.name}</div>
            <div className="item-note">{memberAffiliationLabel(member, data.canViewFull)}</div>
            {selected && <div className="member-detail">
              <div className="member-expanded-profile">
                <div className="item-note">出身：{member.hometown || "未登録"} / 吹奏楽：{member.band_years ?? "未登録"}年 / MBTI：{member.mbti || "未登録"}</div>
                <div className="item-note">係：{member.duty || "なし"}</div>
                <div className="item-note">授業遅刻になる曜日：{classLateWeekdayText(member.classLateWeekdays)}</div>
                {data.canViewFull && <div className="item-note">電話：{member.phone || "未登録"} / メール：{member.email || "未登録"} / 入部日：{member.join_date ? formatDateWithWeekday(member.join_date) : "未登録"}</div>}
                {data.canManage && <div className="item-note">最終ログイン：{formatLoginDateTime(member.lastLoginAt)}</div>}
                {data.canManage && <div className="item-note">暗証番号：{member.pinStatus === "設定済み" ? "設定済み（内容は安全のため表示されません）" : "未設定（初回ログインは0）"}</div>}
              </div>
              <div className="member-detail-metrics">
                <span>出席率：<strong>{member.attendanceRate == null ? "—" : `${member.attendanceRate}%`}</strong></span>
                <span>承認済み記録：{member.attendanceRecords || 0}回</span>
              </div>
              {data.canManage && <button type="button" className="small-button card-action" onClick={(event) => { event.stopPropagation(); startEdit(member); }}>編集</button>}
              {data.canManage && <button type="button" className="small-button card-action" onClick={(event) => { event.stopPropagation(); resetMemberPin(member); }}>暗証番号をリセット</button>}
              {data.canManage && <button type="button" className="small-button danger-button card-action" onClick={(event) => { event.stopPropagation(); removeMember(member); }}>削除</button>}
              <div className="item-title small-title">今わかっている欠席・遅刻予定</div>
              <div className="member-plan-list">
                {(member.knownPlans || []).map((plan, index) => <div className="member-plan" key={`${member.id}-${plan.date}-${index}`}>
                  <span className={plan.status === "欠席" ? "notice-badge important" : "notice-badge"}>{plan.status}</span>
                  <div>
                    <div>{formatDateWithWeekday(plan.date)}｜{plan.title || plan.eventType}</div>
                    <div className="item-note">承認：{plan.approvalStatus || "未確認"}{plan.reason ? ` / 理由：${plan.reason}` : ""}</div>
                  </div>
                </div>)}
                {(member.knownPlans || []).length === 0 && <div className="item-note">今わかっている欠席・遅刻予定はありません。</div>}
              </div>
            </div>}
          </div>
          <div className="member-row-actions">
            {member.role !== "顧問" && <span>{member.grade}年</span>}
            <span className={memberRoleClass(member.role)}>{memberRoleLabel(member.role)}</span>
            <span className="member-toggle-label">{selected ? "閉じる" : "詳細"}</span>
          </div>
        </div>;
      })}
    </div></Section>
    {data.canManage && <button className="ghost-button" onClick={() => setActive("ops")}>運営に戻る</button>}
  </>;
}

function StatisticsScreen({ token, setActive, currentUser }) {
  const currentMonth = new Date().toISOString().slice(0, 7);
  const [month, setMonth] = useState(currentMonth);
  const [data, setData] = useState(null);
  const [memberAttendance, setMemberAttendance] = useState([]);
  const [selectedMemberId, setSelectedMemberId] = useState("");
  useEffect(() => {
    fetchApi(`${API_BASE}/api/statistics?month=${encodeURIComponent(month)}`, { headers: { Authorization: `Bearer ${token}` } })
      .then((response) => response.json()).then(setData);
    if (currentUser?.role === "管理者") {
      fetchApi(`${API_BASE}/api/admin/member-attendance?month=${encodeURIComponent(month)}`, { headers: { Authorization: `Bearer ${token}` } })
        .then((response) => response.json())
        .then((payload) => {
          const items = payload.items || [];
          setMemberAttendance(items);
          setSelectedMemberId((current) => current || String(items[0]?.id || ""));
        });
    }
  }, [token, currentUser?.role, month]);
  const summary = data?.summary || {};
  const selectedMember = memberAttendance.find((item) => String(item.id) === String(selectedMemberId));
  return <>
    <ScreenIntro eyebrow="STATISTICS" title="運営向け詳細統計" text="月を指定し、回答・承認・出欠区分まで含めて部活動の状況を分析します。" />
    <Section title="集計する月"><div className="card"><label className="field-label">対象月<input className="input" type="month" value={month} onChange={(event) => setMonth(event.target.value)} /></label></div></Section>
    <Section title="全体サマリー"><div className="grid two wide-grid">
      <Metric label="全体出席率" value={summary.rate == null ? "—" : `${summary.rate}%`} note="承認済み記録" />
      <Metric label="回答率" value={summary.answerRate == null ? "—" : `${summary.answerRate}%`} note={`${summary.eventCount || 0}件の予定 / ${summary.memberCount || 0}人`} />
    </div></Section>
    <Section title="詳細内訳"><DetailedAttendanceBreakdown stats={summary} /></Section>
    <Section title="パート別出席率"><RateBars items={data?.parts || []} /></Section>
    <Section title="日別出席率"><RateBars items={(data?.daily || []).map((item) => ({...item, label: formatDateWithWeekday(item.label)}))} /></Section>
    <Section title="予定種別ごとの出席率"><RateBars items={data?.eventTypes || []} /></Section>
    {currentUser?.role === "管理者" && <Section title="部員別の出席状況">
      <div className="card member-attendance-panel">
        <label className="field-label">確認する部員<select className="input" value={selectedMemberId} onChange={(event) => setSelectedMemberId(event.target.value)}>
          {memberAttendance.map((item) => <option value={item.id} key={item.id}>{item.name}（{item.part}）</option>)}
        </select></label>
        {selectedMember && <>
          <div className="item-note">{selectedMember.grade}年 / {selectedMember.part} / {memberRoleLabel(selectedMember.role)}</div>
          <AttendanceOverview stats={selectedMember.stats} />
          <DetailedAttendanceBreakdown stats={selectedMember.stats} />
          <div className="item-title admin-detail-heading">予定種別ごとの内訳</div>
          <div className="admin-event-type-grid">{(selectedMember.eventTypes || []).map((item) => <div className="card" key={item.label}><strong>{item.label}</strong><span>対象 {item.scheduled} / 出席 {item.attended} / 欠席 {item.absent} / 未回答 {item.unanswered}</span></div>)}</div>
          <div className="item-title admin-detail-heading">予定ごとの回答詳細（運営者のみ）</div>
          <div className="admin-attendance-table"><div className="admin-attendance-row admin-attendance-head"><span>日付・予定</span><span>回答</span><span>承認</span><span>理由・欠席区分</span></div>
            {(selectedMember.details || []).map((detail) => <div className="admin-attendance-row" key={detail.eventId}>
              <span><strong>{formatDateWithWeekday(detail.date)}</strong><small>{detail.title} / {detail.eventType}</small></span>
              <span>{detail.status}</span><span>{detail.approvalStatus}</span><span>{detail.reason || "—"}{detail.absenceType !== "なし" ? `（${detail.absenceType}）` : ""}</span>
            </div>)}
          </div>
        </>}
        {memberAttendance.length === 0 && <div className="empty-card">対象の部員がいません。</div>}
      </div>
      <button className="ghost-button card-action" onClick={() => setActive("publications")}>この月の分析をホーム公開する</button>
    </Section>}
    <button className="ghost-button" onClick={() => setActive("ops")}>運営に戻る</button>
  </>;
}

function RemindersScreen({ token, setActive }) {
  const [data, setData] = useState({ event: null, members: [] });
  useEffect(() => {
    fetchApi(`${API_BASE}/api/attendance/reminders`, { headers: { Authorization: `Bearer ${token}` } })
      .then((response) => response.json()).then(setData);
  }, [token]);
  return <>
    <ScreenIntro eyebrow="REMINDERS" title="出席未回答" text="直近の予定にまだ回答していない部員を確認します。" />
    <Section title={data.event ? `${formatDateWithWeekday(data.event.date)}｜${data.event.title}` : "対象予定なし"}>
      <div className="grid two wide-grid"><Metric label="未回答" value={`${data.members.length}人`} note="回答待ち" /></div>
      <div className="list">{data.members.map((member) => <div className="card list-item" key={member.id}><div><div className="item-title">{member.name}</div><div className="item-note">{member.part} / {member.grade}年</div></div></div>)}</div>
    </Section>
    <button className="ghost-button" onClick={() => setActive("ops")}>運営に戻る</button>
  </>;
}

function PublicationsScreen({ token, setActive, currentUser }) {
  const currentMonth = new Date().toISOString().slice(0, 7);
  const [items, setItems] = useState([]);
  const [kind, setKind] = useState("overall_rate");
  const [period, setPeriod] = useState(currentMonth);
  const [title, setTitle] = useState("月間全体出席率");
  const [audienceType, setAudienceType] = useState("all");
  const [audienceValue, setAudienceValue] = useState("");
  const [directory, setDirectory] = useState({ members: [], parts: [], roles: [] });
  const [memberId, setMemberId] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    const response = await fetchApi(`${API_BASE}/api/publications`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (response.ok) setItems((await response.json()).items || []);
  }
  useEffect(() => {
    if (!token) return;
    load();
    fetchApi(`${API_BASE}/api/members`, { headers: { Authorization: `Bearer ${token}` } })
      .then((response) => response.json())
      .then((data) => {
        setDirectory(data);
        setMemberId((current) => current || String(data.members?.[0]?.id || ""));
      });
  }, [token]);

  function changeKind(nextKind) {
    setKind(nextKind);
    const titles = {
      ranking: "月間出席ランキング", overall_rate: "月間全体出席率", answer_rate: "月間回答率",
      attendance_breakdown: "月間出欠内訳", part_rates: "パート別出席率", daily_rates: "日別出席率",
      event_type_rates: "予定種別出席率", member_attendance: "部員別出席状況", member_event_types: "部員別・予定種別内訳",
    };
    setTitle(titles[nextKind] || "公開情報");
  }

  const audienceOptions = audienceType === "role"
    ? directory.roles || []
    : audienceType === "part"
      ? directory.parts || []
      : audienceType === "member"
        ? directory.members || []
        : [];

  async function publish() {
    const response = await fetchApi(`${API_BASE}/api/publications`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        kind, title, period,
        audienceType,
        audienceValue: audienceType === "member" ? String(audienceValue || audienceOptions[0]?.id || "") : (audienceValue || audienceOptions[0] || null),
        memberId: ["member_attendance", "member_event_types"].includes(kind) ? Number(memberId) : null,
      }),
    });
    if (response.ok) {
      setMessage("指定した公開範囲のホームへ公開しました。");
      load();
    } else {
      const data = await response.json().catch(() => ({}));
      setMessage(data.detail || "公開できませんでした。");
    }
  }

  async function toggle(id) {
    await fetchApi(`${API_BASE}/api/publications/${id}/visibility`, {
      method: "PATCH",
      headers: { Authorization: `Bearer ${token}` },
    });
    load();
  }

  async function remove(id) {
    await fetchApi(`${API_BASE}/api/publications/${id}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    load();
  }

  if (currentUser?.role !== "管理者") return <div className="card error-card">管理者のみ利用できます。</div>;
  return <>
    <ScreenIntro eyebrow="PUBLIC BOARD" title="公開設定" text="運営情報を1項目ずつ選び、それぞれ異なる範囲へ公開できます。個人の回答理由は公開されません。" />
    {message && <div className="card success-card">{message}</div>}
    <Section title="新しく公開">
      <div className="card publication-form">
        <label className="field-label">公開する情報（1項目）<select className="input" value={kind} onChange={(event) => changeKind(event.target.value)}><option value="overall_rate">全体出席率</option><option value="answer_rate">回答率</option><option value="attendance_breakdown">出席・遅刻・早退・欠席などの内訳</option><option value="part_rates">パート別出席率グラフ</option><option value="daily_rates">日別出席率グラフ</option><option value="event_type_rates">予定種別出席率グラフ</option><option value="ranking">月間ランキング</option><option value="member_attendance">部員1人の出席概要</option><option value="member_event_types">部員1人の予定種別内訳</option></select></label>
        <label className="field-label">対象月<input className="input" type="month" value={period} onChange={(event) => setPeriod(event.target.value)} /></label>
        {["member_attendance", "member_event_types"].includes(kind) && <label className="field-label">対象部員<select className="input" value={memberId} onChange={(event) => setMemberId(event.target.value)}>{(directory.members || []).map((member) => <option value={member.id} key={member.id}>{member.name}（{member.part}）</option>)}</select></label>}
        <label className="field-label">公開タイトル<input className="input" value={title} onChange={(event) => setTitle(event.target.value)} /></label>
        <label className="field-label">公開範囲<select className="input" value={audienceType} onChange={(event) => { setAudienceType(event.target.value); setAudienceValue(""); }}><option value="all">全員</option><option value="role">役職を指定</option><option value="part">パートを指定</option><option value="member">個人を指定</option></select></label>
        {audienceType !== "all" && <label className="field-label">公開先<select className="input" value={audienceValue} onChange={(event) => setAudienceValue(event.target.value)}>{audienceOptions.map((option) => {
          const value = audienceType === "member" ? option.id : option;
          const label = audienceType === "member" ? `${option.name}（${option.part}）` : audienceType === "role" ? memberRoleLabel(option) : option;
          return <option value={value} key={value}>{label}</option>;
        })}</select></label>}
        <button className="primary-button" disabled={Boolean(currentUser?.readOnly)} onClick={publish}>指定範囲のホームへ公開</button>
      </div>
    </Section>
    <Section title="公開データの管理">
      <PublicationCards items={items} manage onToggle={toggle} onDelete={remove} />
      {items.length === 0 && <div className="card empty-card">公開データはありません。</div>}
    </Section>
    <button className="ghost-button" onClick={() => setActive("ops")}>運営に戻る</button>
  </>;
}

function EventManagementScreen({ token, currentUser, setActive }) {
  const today = new Date().toISOString().slice(0, 10);
  const [month, setMonth] = useState(today.slice(0, 7));
  const [eventsData, setEventsData] = useState([]);
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState({
    date: today,
    startTime: "09:00",
    endTime: "12:00",
    eventType: "通常練習",
    title: "",
    location: "",
    memo: "",
    teacherVisit: false,
  });
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const eventFormRef = useRef(null);
  const [editScrollRequest, setEditScrollRequest] = useState(0);

  const canEdit = currentUser?.permissions?.canEditEvents;

  async function loadEvents(selectedMonth = month) {
    setError("");
    try {
      const response = await fetchApi(`${API_BASE}/api/events?month=${selectedMonth}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "予定を読み込めませんでした");
      setEventsData(data.events || []);
    } catch (err) {
      setError(err.message || "予定を読み込めませんでした");
    }
  }

  useEffect(() => {
    if (token && canEdit) loadEvents(month);
  }, [token, month, canEdit]);

  useEffect(() => {
    if (editScrollRequest === 0) return undefined;
    const timer = window.setTimeout(() => {
      eventFormRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 80);
    return () => window.clearTimeout(timer);
  }, [editScrollRequest]);

  function updateForm(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function resetForm() {
    setEditingId(null);
    setForm({
      date: `${month}-01`,
      startTime: "09:00",
      endTime: "12:00",
      eventType: "通常練習",
      title: "",
      location: "",
      memo: "",
      teacherVisit: false,
    });
  }

  function beginEdit(event) {
    setEditingId(event.id);
    setForm({
      date: event.date,
      startTime: event.startTime || "09:00",
      endTime: event.endTime || "12:00",
      eventType: event.type,
      title: event.title,
      location: event.location || "",
      memo: event.description === "練習内容が登録されるとここに表示されます。" ? "" : event.description || "",
      teacherVisit: Boolean(event.teacherVisit),
    });
    setMessage("");
    setError("");
    setEditScrollRequest((current) => current + 1);
  }

  async function saveEvent(event) {
    event.preventDefault();
    setLoading(true);
    setMessage("");
    setError("");
    try {
      const response = await fetchApi(
        editingId ? `${API_BASE}/api/events/${editingId}` : `${API_BASE}/api/events`,
        {
          method: editingId ? "PATCH" : "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify(form),
        },
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "予定を保存できませんでした");
      const savedMonth = form.date.slice(0, 7);
      setMonth(savedMonth);
      setMessage(editingId ? "予定を更新しました。" : "予定を登録しました。");
      resetForm();
      await loadEvents(savedMonth);
    } catch (err) {
      setError(err.message || "予定を保存できませんでした");
    } finally {
      setLoading(false);
    }
  }

  async function removeEvent(eventId) {
    if (!window.confirm("この予定を削除しますか？")) return;
    setError("");
    setMessage("");
    try {
      const response = await fetchApi(`${API_BASE}/api/events/${eventId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "予定を削除できませんでした");
      setMessage("予定を削除しました。");
      if (editingId === eventId) resetForm();
      await loadEvents();
    } catch (err) {
      setError(err.message || "予定を削除できませんでした");
    }
  }

  if (!canEdit) {
    return (
      <div className="card error-card">
        この画面は部長・副部長・管理者のみ利用できます。
      </div>
    );
  }

  return (
    <>
      <ScreenIntro
        eyebrow="EVENT MANAGEMENT"
        title="予定を管理"
        text="練習や本番の予定を登録し、カレンダーへ反映できます。"
      />
      {error && <div className="card error-card">{error}</div>}
      {message && <div className="card success-card">{message}</div>}
      <div className="event-form-scroll-target" ref={eventFormRef}>
      <Section title={editingId ? "予定を編集" : "予定を登録"}>
        <form className="card event-form" onSubmit={saveEvent}>
          <div className="event-datetime-grid event-form-wide">
            <label className="field-label event-date-field">日付<input className="input" type="date" required value={form.date} onChange={(event) => updateForm("date", event.target.value)} />{form.date && <span className="item-note">{formatDateWithWeekday(form.date)}</span>}</label>
            <label className="field-label">開始<input className="input" type="time" value={form.startTime} onChange={(event) => updateForm("startTime", event.target.value)} /></label>
            <label className="field-label">終了<input className="input" type="time" value={form.endTime} onChange={(event) => updateForm("endTime", event.target.value)} /></label>
          </div>
          <label className="field-label">種別<select className="input" value={form.eventType} onChange={(event) => updateForm("eventType", event.target.value)}>{eventTypes.map((type) => <option value={type} key={type}>{type}</option>)}</select></label>
          <label className="field-label event-form-wide">タイトル<input className="input" required placeholder="例：コンクール曲 合奏" value={form.title} onChange={(event) => updateForm("title", event.target.value)} /></label>
          <label className="field-label event-form-wide">場所<input className="input" placeholder="例：音楽室" value={form.location} onChange={(event) => updateForm("location", event.target.value)} /></label>
          <label className={`teacher-visit-toggle event-form-wide ${form.teacherVisit ? "active" : ""}`}>
            <input type="checkbox" checked={form.teacherVisit} onChange={(event) => updateForm("teacherVisit", event.target.checked)} />
            <span className="teacher-visit-toggle-icon"><User size={20} /></span>
            <span><strong>先生来校</strong><small>先生（指揮者）が来る予定としてカレンダーにマークします</small></span>
          </label>
          <label className="field-label event-form-wide">メモ<textarea className="input" rows={3} value={form.memo} onChange={(event) => updateForm("memo", event.target.value)} /></label>
          <div className="event-form-actions event-form-wide">
            <button className="primary-button" disabled={loading}>{loading ? "保存中" : editingId ? "変更を保存" : "予定を登録"}</button>
            {editingId && <button className="ghost-button" type="button" onClick={resetForm}>編集をやめる</button>}
          </div>
        </form>
      </Section>
      </div>
      <Section title="登録済みの予定" action={<input className="month-input" type="month" value={month} onChange={(event) => setMonth(event.target.value)} />}>
        <div className="list">
          {eventsData.length === 0 && <div className="card empty-card">この月の予定はありません。</div>}
          {eventsData.map((event) => (
            <div className="card managed-event" key={event.id}>
              <EventSummaryCard event={event} bare collapsibleDescription />
              <div className="managed-event-actions">
                <button className="small-button" onClick={() => beginEdit(event)}>編集</button>
                <button className="small-button danger-button" onClick={() => removeEvent(event.id)}>削除</button>
              </div>
            </div>
          ))}
        </div>
      </Section>
      <button className="ghost-button" onClick={() => setActive("ops")}>運営に戻る</button>
    </>
  );
}

function AbsenceReportScreen({ token, currentUser, setActive }) {
  const [data, setData] = useState({ items: [], parts: [], roles: [] });
  const [part, setPart] = useState("");
  const [targetRoles, setTargetRoles] = useState([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [sharing, setSharing] = useState(false);
  const [periodType, setPeriodType] = useState("day");
  const [selectedDate, setSelectedDate] = useState(todayKey());

  useEffect(() => {
    if (currentUser?.role !== "管理者") return;
    fetchApi(`${API_BASE}/api/admin/absence-report`, { headers: { Authorization: `Bearer ${token}` } })
      .then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.detail || "一覧を読み込めませんでした");
        setData(body);
      })
      .catch((err) => setError(err.message || "一覧を読み込めませんでした"));
  }, [token, currentUser?.role]);

  const period = periodType === "week"
    ? weekRangeForDate(selectedDate)
    : periodType === "month"
      ? monthRangeForDate(selectedDate)
    : periodType === "day"
      ? { startDate: selectedDate, endDate: selectedDate }
      : { startDate: todayKey(), endDate: null };
  const visibleRows = data.items.filter((row) => {
    if (part && row.part !== part) return false;
    if (row.date < period.startDate) return false;
    return !period.endDate || row.date <= period.endDate;
  });

  function toggleTargetRole(role) {
    setTargetRoles((current) => current.includes(role) ? current.filter((item) => item !== role) : [...current, role]);
  }

  async function shareReport() {
    if (targetRoles.length === 0) {
      setError("共有先の役職を1つ以上選択してください。");
      return;
    }
    setSharing(true); setError(""); setMessage("");
    try {
      const response = await fetchApi(`${API_BASE}/api/admin/absence-report/shares`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ targetRoles, part: part || null, startDate: period.startDate, endDate: period.endDate }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "共有できませんでした");
      setMessage(`${body.targetCount}人に、表${body.itemCount}件を共有しました。`);
    } catch (err) {
      setError(err.message || "共有できませんでした");
    } finally {
      setSharing(false);
    }
  }

  if (currentUser?.role !== "管理者") return <div className="card error-card">管理者のみ利用できます。</div>;
  return <>
    <ScreenIntro eyebrow="ABSENCE REPORT" title="欠席・遅刻一覧" text="全部員・全パートの今後の欠席、遅刻、早退申請を一覧で確認し、役職を指定して共有できます。" />
    {error && <div className="card error-card">{error}</div>}
    {message && <div className="card success-card">{message}</div>}
    <Section title="公開する期間">
      <div className="card form-stack">
        <div className="pill-row">
          <button className={`pill ${periodType === "day" ? "active" : ""}`} onClick={() => setPeriodType("day")}>日付指定</button>
          <button className={`pill ${periodType === "week" ? "active" : ""}`} onClick={() => setPeriodType("week")}>週単位</button>
          <button className={`pill ${periodType === "month" ? "active" : ""}`} onClick={() => setPeriodType("month")}>月単位</button>
          <button className={`pill ${periodType === "all" ? "active" : ""}`} onClick={() => setPeriodType("all")}>今後すべて</button>
        </div>
        {periodType !== "all" && <input className="input" type="date" value={selectedDate} onChange={(event) => setSelectedDate(event.target.value)} />}
        <div className="item-note">対象期間：{formatDateWithWeekday(period.startDate)}{period.endDate && period.endDate !== period.startDate ? ` 〜 ${formatDateWithWeekday(period.endDate)}` : ""}</div>
      </div>
    </Section>
    <Section title={`一覧 ${visibleRows.length}件`} action={<select className="input" value={part} onChange={(event) => setPart(event.target.value)}><option value="">全部員・全パート</option>{data.parts.map((item) => <option key={item}>{item}</option>)}</select>}>
      <AbsenceReportTable rows={visibleRows} />
    </Section>
    <Section title="この表を共有">
      <div className="card form-stack">
        <div className="item-note">共有する相手の役職を複数選択できます。</div>
        <div className="role-share-grid">
          {data.roles.map((role) => (
            <label className="check-line" key={role}>
              <input type="checkbox" checked={targetRoles.includes(role)} onChange={() => toggleTargetRole(role)} />
              {memberRoleLabel(role)}
            </label>
          ))}
        </div>
        <button className="primary-button" onClick={shareReport} disabled={sharing || targetRoles.length === 0}>{sharing ? "共有中" : "選択した役職へ共有"}</button>
      </div>
    </Section>
    <button className="ghost-button" onClick={() => setActive("ops")}>運営に戻る</button>
  </>;
}

function AdminDesktopOverview({ summary, usageStats, maintenanceEnabled, leaveFeature, setActive }) {
  const [selectedMemberAnalysisId, setSelectedMemberAnalysisId] = useState("");
  const rateRows = [
    ["出欠回答率", usageStats?.attendance?.rate],
    ["利用者率", usageStats?.usage?.activeUserRate],
    ["申請処理率", usageStats?.workflow?.processingRate],
  ];
  const phaseLabel = usageStats?.lifecycle?.phase === "trial"
    ? "試行期間"
    : usageStats?.lifecycle?.phase === "release" ? "本リリース" : "開始前";
  const statusLabel = (value, enabled, disabled) => value === null ? "確認中" : value ? enabled : disabled;
  const trendMax = Math.max(1, ...(usageStats?.trends || []).map((item) => Math.max(item.responses || 0, item.logins || 0)));
  const breakdown = usageStats?.attendance?.breakdown || {};
  const breakdownTotal = ["present", "absent", "late", "early"].reduce((total, key) => total + (breakdown[key] || 0), 0);
  const presentShare = breakdownTotal ? Math.round((breakdown.present || 0) * 100 / breakdownTotal) : 0;
  const lateShare = breakdownTotal ? Math.round(((breakdown.late || 0) + (breakdown.early || 0)) * 100 / breakdownTotal) : 0;
  const alerts = [
    summary.pendingApprovals > 0 ? { tone: "danger", title: `承認待ちが${summary.pendingApprovals}件あります`, action: "approvals", label: "承認する" } : null,
    summary.unanswered > 0 ? { tone: "warning", title: `次回予定に未回答者が${summary.unanswered}人います`, action: "reminders", label: "確認する" } : null,
    usageStats?.usage?.activeUserRate < 80 ? { tone: "info", title: `期間内利用者率が${usageStats.usage.activeUserRate}%です`, action: "members", label: "部員を見る" } : null,
  ].filter(Boolean);
  const selectedMemberAnalysis = (usageStats?.memberAnalytics || []).find((item) => item.id === Number(selectedMemberAnalysisId));
  return (
    <section className="admin-desktop-dashboard" aria-label="管理者向け運営分析">
      <div className="admin-desktop-heading">
        <div>
          <div className="intro-eyebrow">DESKTOP COMMAND CENTER</div>
          <h2>運営分析ダッシュボード</h2>
          <p>スマホでは日々の操作を、パソコンでは状況把握と分析をまとめて行えます。</p>
        </div>
        <div className="admin-desktop-period">
          {usageStats ? `${formatDateWithWeekday(usageStats.startDate)}〜${formatDateWithWeekday(usageStats.endDate)}` : "データを集計中"}
        </div>
      </div>

      <div className="admin-desktop-kpis">
        <Metric label="在籍部員" value={summary.memberCount === null ? "—" : `${summary.memberCount}人`} note="現在の運用対象" />
        <Metric label="期間内利用者" value={usageStats ? `${usageStats.usage.activeUsers}人` : "—"} note={usageStats ? `${usageStats.usage.logins}回ログイン` : "集計中"} />
        <Metric label="対象予定" value={usageStats ? `${usageStats.attendance.events}件` : "—"} note={usageStats ? `出欠回答 ${usageStats.attendance.responses}件` : "集計中"} />
        <Metric label="承認待ち" value={summary.pendingApprovals === null ? "—" : `${summary.pendingApprovals}件`} note="現在の未処理申請" />
        <Metric label="次回未回答" value={summary.unanswered === null ? "—" : `${summary.unanswered}人`} note={summary.reminderEvent ? formatDateWithWeekday(summary.reminderEvent.date) : "次の予定"} />
        <Metric label="平均承認時間" value={usageStats?.workflow?.averageApprovalHours == null ? "—" : `${usageStats.workflow.averageApprovalHours}時間`} note="申請から処理まで" />
      </div>

      <div className="admin-insight-strip">
        {alerts.length ? alerts.map((alert) => <div className={`admin-insight ${alert.tone}`} key={alert.title}>
          <span>{alert.title}</span><button onClick={() => setActive(alert.action)}>{alert.label}</button>
        </div>) : <div className="admin-insight success"><span>現在、優先対応が必要な項目はありません。</span><strong>良好</strong></div>}
      </div>

      <div className="card admin-analysis-panel admin-member-analysis">
        <div className="admin-panel-heading">
          <div><div className="item-title">部員別分析</div><div className="item-note">部員を選ぶと、指定期間の出欠状況を個別に確認できます</div></div>
          <select className="input" value={selectedMemberAnalysisId} onChange={(event) => setSelectedMemberAnalysisId(event.target.value)}>
            <option value="">部員を選択</option>
            {(usageStats?.memberAnalytics || []).map((member) => <option value={member.id} key={member.id}>{member.name}（{member.part}・{member.grade}年）</option>)}
          </select>
        </div>
        {selectedMemberAnalysis ? <div className="admin-member-analysis-body">
          <div className="admin-member-profile"><strong>{selectedMemberAnalysis.name}</strong><span>{selectedMemberAnalysis.part}・{selectedMemberAnalysis.grade}年</span></div>
          <div className="admin-member-metrics">
            <Metric label="回答率" value={`${selectedMemberAnalysis.responseRate}%`} note={`${selectedMemberAnalysis.responses}/${selectedMemberAnalysis.opportunities}件`} />
            <Metric label="出席率" value={`${selectedMemberAnalysis.attendanceRate}%`} note={`通常出席 ${selectedMemberAnalysis.present}回`} />
            <Metric label="未回答" value={`${selectedMemberAnalysis.unanswered}件`} note="指定期間内" />
            <Metric label="承認待ち" value={`${selectedMemberAnalysis.pending}件`} note="現在の処理状況" />
          </div>
          <div className="admin-member-breakdown">
            <span className="attendance-pill attended">出席 {selectedMemberAnalysis.present}</span>
            <span className="attendance-pill pending">遅刻 {selectedMemberAnalysis.late}</span>
            <span className="attendance-pill pending">早退 {selectedMemberAnalysis.early}</span>
            <span className="attendance-pill absent">欠席 {selectedMemberAnalysis.absent}</span>
          </div>
        </div> : <div className="admin-member-analysis-empty">確認したい部員を右上から選択してください。</div>}
      </div>

      <div className="admin-youtube-grid">
        <div className="card admin-analysis-panel admin-trend-panel">
          <div className="admin-panel-heading"><div><div className="item-title">利用と回答の推移</div><div className="item-note">直近最大31日・予定がある日を表示</div></div><div className="admin-chart-legend"><span className="responses">出欠回答 {usageStats?.attendance?.responses || 0}件</span><span className="logins">ログイン {usageStats?.usage?.logins || 0}回</span></div></div>
          {(usageStats?.trends || []).length ? <div className="admin-trend-chart">
            {usageStats.trends.map((item) => <div className="admin-trend-day" key={item.date} title={`${formatDateWithWeekday(item.date)}：回答${item.responses}件・ログイン${item.logins}回`}>
              <div className="admin-trend-bars">
                <div className="admin-trend-bar-column"><b>{item.responses}</b><i className="responses" style={{ height: item.responses ? `${Math.max(4, item.responses * 100 / trendMax)}%` : 0 }} /></div>
                <div className="admin-trend-bar-column"><b>{item.logins}</b><i className="logins" style={{ height: item.logins ? `${Math.max(4, item.logins * 100 / trendMax)}%` : 0 }} /></div>
              </div>
              <small>{String(item.date).slice(5).replace("-", "/")}</small>
            </div>)}
          </div> : <div className="empty-card">この期間の推移データはありません。</div>}
        </div>
        <div className="card admin-analysis-panel admin-breakdown-panel">
          <div className="item-title">承認済み出欠の内訳</div>
          <div className="admin-donut" style={{ "--present-share": `${presentShare * 3.6}deg`, "--late-share": `${(presentShare + lateShare) * 3.6}deg` }}><div><strong>{breakdownTotal}</strong><span>回答</span></div></div>
          <div className="admin-breakdown-list">
            <span><i className="present" />出席 <strong>{breakdown.present || 0}</strong></span>
            <span><i className="late" />遅刻・早退 <strong>{(breakdown.late || 0) + (breakdown.early || 0)}</strong></span>
            <span><i className="absent" />欠席 <strong>{breakdown.absent || 0}</strong></span>
            <span><i className="pending" />承認待ち <strong>{breakdown.pending || 0}</strong></span>
          </div>
        </div>
      </div>

      <div className="admin-youtube-grid equal">
        <div className="card admin-analysis-panel">
          <div className="admin-panel-heading"><div><div className="item-title">パート別パフォーマンス</div><div className="item-note">回答率が低い順</div></div></div>
          <div className="admin-data-table"><div className="head"><span>パート</span><span>部員</span><span>回答率</span><span>出席率</span></div>
            {[...(usageStats?.parts || [])].sort((a, b) => a.responseRate - b.responseRate).map((row) => <div key={row.part}><span>{row.part}</span><span>{row.members}人</span><strong>{row.responseRate}%</strong><span>{row.attendanceRate}%</span></div>)}
          </div>
        </div>
        <div className="card admin-analysis-panel">
          <div className="admin-panel-heading"><div><div className="item-title">回答フォローが必要な部員</div><div className="item-note">回答率が低い部員を自動抽出</div></div><button onClick={() => setActive("members")}>部員一覧</button></div>
          <div className="admin-attention-list">
            {(usageStats?.memberAttention || []).map((row) => <div key={row.id}><span><strong>{row.name}</strong><small>{row.part}</small></span><span>未回答 {row.unanswered}</span><b>{row.responseRate}%</b></div>)}
            {!usageStats?.memberAttention?.length && <div className="item-note">対象データはありません。</div>}
          </div>
        </div>
      </div>

      <div className="card admin-analysis-panel">
        <div className="admin-panel-heading"><div><div className="item-title">回答率が低い予定</div><div className="item-note">連絡や回答依頼を優先したい予定</div></div><button onClick={() => setActive("reminders")}>未回答を確認</button></div>
        <div className="admin-event-performance">
          {(usageStats?.eventPerformance || []).map((row) => <div key={row.id}><span><strong>{row.title}</strong><small>{formatDateWithWeekday(row.date)}</small></span><span>{row.responses}/{row.opportunities}回答</span><b>{row.responseRate}%</b></div>)}
          {!usageStats?.eventPerformance?.length && <div className="item-note">対象データはありません。</div>}
        </div>
      </div>

      <div className="admin-desktop-columns">
        <div className="card admin-analysis-panel">
          <div className="item-title">主要な達成率</div>
          <div className="admin-rate-list">
            {rateRows.map(([label, value]) => <div className="admin-rate-row" key={label}>
              <div><span>{label}</span><strong>{value == null ? "—" : `${value}%`}</strong></div>
              <div className="admin-rate-track"><span style={{ width: `${Math.max(0, Math.min(100, value || 0))}%` }} /></div>
            </div>)}
          </div>
        </div>
        <div className="card admin-analysis-panel">
          <div className="item-title">運用状態</div>
          <dl className="admin-status-list">
            <div><dt>運用段階</dt><dd>{phaseLabel}</dd></div>
            <div><dt>システム</dt><dd>{statusLabel(maintenanceEnabled, "メンテナンス中", "通常稼働中")}</dd></div>
            <div><dt>休暇権利</dt><dd>{statusLabel(leaveFeature, "稼働中", "停止中")}</dd></div>
            <div><dt>運用日数</dt><dd>{usageStats?.daysInOperation ? `${usageStats.daysInOperation}日` : "—"}</dd></div>
          </dl>
        </div>
      </div>

      <div className="card admin-analysis-panel">
        <div className="item-title">期間内の活動</div>
        <div className="admin-activity-grid">
          <div><span>申請</span><strong>{usageStats?.workflow?.requests ?? "—"}</strong><small>処理済み {usageStats?.workflow?.processed ?? "—"}</small></div>
          <div><span>お知らせ</span><strong>{usageStats?.engagement?.announcements ?? "—"}</strong><small>配信件数</small></div>
          <div><span>To Do</span><strong>{usageStats?.engagement?.todos ?? "—"}</strong><small>完了 {usageStats?.engagement?.completedTodos ?? "—"}</small></div>
          <div><span>パート連絡</span><strong>{usageStats?.engagement?.partMemos ?? "—"}</strong><small>共有件数</small></div>
          <div><span>誕生日メッセージ</span><strong>{usageStats?.engagement?.birthdayMessages ?? "—"}</strong><small>リアクション {usageStats?.engagement?.birthdayReactions ?? "—"}</small></div>
        </div>
      </div>

      <div className="admin-desktop-actions">
        <button className="primary-button" onClick={() => setActive("approvals")}>承認を確認</button>
        <button className="ghost-button" onClick={() => setActive("event-management")}>予定を管理</button>
        <button className="ghost-button" onClick={() => setActive("members")}>部員を管理</button>
        <button className="ghost-button" onClick={() => setActive("statistics")}>詳細統計を見る</button>
        <button className="ghost-button" onClick={() => setActive("absence-report")}>欠席・遅刻一覧</button>
        <button className="ghost-button" onClick={() => setActive("publications")}>公開設定</button>
      </div>
    </section>
  );
}

function LeadershipOverview({ data, loading, error, setActive, role }) {
  const summary = data?.summary || {};
  const sortedParts = [...(data?.parts || [])].sort((a, b) => a.responseRate - b.responseRate);
  return (
    <section className="leadership-dashboard" aria-label="部長・副部長向け運営分析">
      <div className="leadership-heading">
        <div>
          <div className="intro-eyebrow">LEADERSHIP OVERVIEW</div>
          <h2>{role}向け運営状況</h2>
          <p>承認や声かけが必要な状況を、部活動の運営目線で確認できます。</p>
        </div>
        {data && <span>{formatDateWithWeekday(data.startDate)}〜{formatDateWithWeekday(data.endDate)}</span>}
      </div>
      {error && <div className="card error-card">{error}</div>}
      {loading && !data && <div className="card empty-card">運営状況を集計しています。</div>}
      {data && <>
        <div className="leadership-kpis">
          <Metric label="回答率" value={summary.responseRate == null ? "—" : `${summary.responseRate}%`} note={`${summary.responses || 0}/${summary.opportunities || 0}件`} />
          <Metric label="出席率" value={summary.attendanceRate == null ? "—" : `${summary.attendanceRate}%`} note="回答者のうち出席・遅刻・早退" />
          <Metric label="承認待ち" value={`${summary.pending || 0}件`} note="直近30日の未処理" />
          <Metric label="欠席" value={`${summary.absent || 0}件`} note={`${summary.events || 0}回の予定を集計`} />
        </div>

        <div className="leadership-grid">
          <div className="card leadership-panel">
            <div className="admin-panel-heading"><div><div className="item-title">今後の予定と注意点</div><div className="item-note">未回答や欠席予定を先に確認</div></div><button onClick={() => setActive("event-management")}>予定管理</button></div>
            <div className="leadership-event-list">
              {(data.upcomingEvents || []).map((event) => <div key={event.id}>
                <span><strong>{event.title}</strong><small>{formatDateWithWeekday(event.date)}</small></span>
                <span className={event.unanswered ? "needs-attention" : ""}>未回答 {event.unanswered}</span>
                <span>欠席 {event.absent}</span>
                <span>遅刻・早退 {event.lateEarly}</span>
                {event.pending > 0 && <button onClick={() => setActive("approvals")}>承認 {event.pending}</button>}
              </div>)}
              {!data.upcomingEvents?.length && <div className="item-note">今後の予定はありません。</div>}
            </div>
          </div>

          <div className="card leadership-panel">
            <div className="admin-panel-heading"><div><div className="item-title">声かけが必要な部員</div><div className="item-note">直近30日で未回答が多い順</div></div><button onClick={() => setActive("reminders")}>未回答確認</button></div>
            <div className="admin-attention-list">
              {(data.memberAttention || []).map((row) => <div key={row.id}><span><strong>{row.name}</strong><small>{row.part}</small></span><span>未回答 {row.unanswered}</span><b>{row.responseRate}%</b></div>)}
              {!data.memberAttention?.length && <div className="item-note">未回答の部員はいません。</div>}
            </div>
          </div>
        </div>

        <div className="card leadership-panel">
          <div className="admin-panel-heading"><div><div className="item-title">パート別の状況</div><div className="item-note">回答率が低いパートから表示</div></div></div>
          <div className="leadership-part-grid">
            {sortedParts.map((part) => <div key={part.part}>
              <div><strong>{part.part}</strong><span>{part.members}人</span></div>
              <div className="leadership-rate-track"><i style={{ width: `${Math.max(0, Math.min(100, part.responseRate))}%` }} /></div>
              <small>回答率 <b>{part.responseRate}%</b>　出席率 {part.attendanceRate}%</small>
            </div>)}
          </div>
        </div>
      </>}
    </section>
  );
}

function OpsScreen({ setActive, currentUser, token }) {
  const currentDate = todayKey();
  const [summary, setSummary] = useState({
    pendingApprovals: null,
    unanswered: null,
    memberCount: null,
    reminderEvent: null,
  });
  const [leaveFeature, setLeaveFeature] = useState(null);
  const [leaveStartedOn, setLeaveStartedOn] = useState(null);
  const [leaveFeatureMessage, setLeaveFeatureMessage] = useState("");
  const [leaveFeatureError, setLeaveFeatureError] = useState("");
  const [leaveFeatureLoading, setLeaveFeatureLoading] = useState(false);
  const [maintenanceEnabled, setMaintenanceEnabled] = useState(null);
  const [maintenanceMessage, setMaintenanceMessage] = useState("");
  const [maintenanceError, setMaintenanceError] = useState("");
  const [maintenanceLoading, setMaintenanceLoading] = useState(false);
  const [usagePeriod, setUsagePeriod] = useState({ startDate: "", endDate: currentDate });
  const [usageStats, setUsageStats] = useState(null);
  const [usageStatsError, setUsageStatsError] = useState("");
  const [usageStatsLoading, setUsageStatsLoading] = useState(false);
  const [operationActionMessage, setOperationActionMessage] = useState("");
  const [operationActionError, setOperationActionError] = useState("");
  const [operationActionLoading, setOperationActionLoading] = useState(false);
  const [leadershipStats, setLeadershipStats] = useState(null);
  const [leadershipStatsError, setLeadershipStatsError] = useState("");
  const [leadershipStatsLoading, setLeadershipStatsLoading] = useState(false);

  async function loadUsageStats(period = usagePeriod) {
    if (currentUser?.role !== "管理者") return;
    setUsageStatsLoading(true);
    setUsageStatsError("");
    try {
      const query = new URLSearchParams(
        Object.fromEntries(Object.entries(period).filter(([, value]) => Boolean(value))),
      ).toString();
      const response = await fetchApi(`${API_BASE}/api/admin/usage-stats?${query}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "利用状況を読み込めませんでした");
      setUsageStats(data);
      setUsagePeriod({ startDate: data.startDate, endDate: data.endDate });
    } catch (err) {
      setUsageStatsError(err.message || "利用状況を読み込めませんでした");
    } finally {
      setUsageStatsLoading(false);
    }
  }

  useEffect(() => {
    loadUsageStats();
  }, [token, currentUser?.role]);

  useEffect(() => {
    if (!["部長", "副部長"].includes(currentUser?.role)) return;
    let ignore = false;
    setLeadershipStatsLoading(true);
    setLeadershipStatsError("");
    fetchApi(`${API_BASE}/api/operations/leadership-stats`, { headers: { Authorization: `Bearer ${token}` } })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || "運営分析を読み込めませんでした");
        if (!ignore) setLeadershipStats(data);
      })
      .catch((err) => { if (!ignore) setLeadershipStatsError(err.message || "運営分析を読み込めませんでした"); })
      .finally(() => { if (!ignore) setLeadershipStatsLoading(false); });
    return () => { ignore = true; };
  }, [token, currentUser?.role]);

  function loadFromSystemStart() {
    const period = { startDate: usageStats?.systemStartedOn || "", endDate: currentDate };
    setUsagePeriod(period);
    loadUsageStats(period);
  }

  async function startOperationPhase(phase) {
    const isTrial = phase === "trial";
    const label = isTrial ? "試行期間" : "本リリース";
    const confirmationText = isTrial ? "試行開始" : "本リリース開始";
    if (!window.confirm(`${label}を開始します。部員・プロフィール・予定は残し、出欠、お知らせ、To Do、ログイン履歴などの運用データを削除します。実行しますか？`)) return;
    const typed = window.prompt(`確認のため「${confirmationText}」と入力してください。`);
    if (typed !== confirmationText) return;
    setOperationActionLoading(true);
    setOperationActionMessage("");
    setOperationActionError("");
    try {
      const response = await fetchApi(`${API_BASE}/api/admin/start-operation-phase/${phase}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `${label}を開始できませんでした`);
      invalidateCache(token);
      setOperationActionMessage(data.message || `${label}を開始しました。`);
      await loadUsageStats({ startDate: "", endDate: currentDate });
    } catch (err) {
      setOperationActionError(err.message || `${label}を開始できませんでした`);
    } finally {
      setOperationActionLoading(false);
    }
  }

  async function advanceYear() {
    if (!window.confirm("新年度へ切り替えます。4年生と関連データを削除し、1〜3年生の学年を1つ上げます。実行しますか？")) return;
    const typed = window.prompt("確認のため「新年度切替」と入力してください。");
    if (typed !== "新年度切替") return;
    setOperationActionLoading(true);
    setOperationActionMessage("");
    setOperationActionError("");
    try {
      const response = await fetchApi(`${API_BASE}/api/admin/advance-year`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "新年度切替に失敗しました");
      invalidateCache(token);
      setOperationActionMessage(`新年度へ切り替えました。卒業削除 ${data.deletedGraduates}人 / 進級 ${data.promotedMembers}人`);
    } catch (err) {
      setOperationActionError(err.message || "新年度切替に失敗しました");
    } finally {
      setOperationActionLoading(false);
    }
  }

  useEffect(() => {
    let ignore = false;
    fetchApi(`${API_BASE}/api/operations/summary`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((response) => {
        if (!response.ok) throw new Error("summary unavailable");
        return response.json();
      })
      .then((data) => {
        if (!ignore) setSummary(data);
      })
      .catch(() => {
        if (!ignore) {
          setSummary({
            pendingApprovals: null,
            unanswered: null,
            memberCount: null,
            reminderEvent: null,
          });
        }
      });
    return () => {
      ignore = true;
    };
  }, [token]);

  useEffect(() => {
    if (currentUser?.role !== "管理者") return;
    let cancelled = false;
    let maintenanceRetry = null;
    fetchApi(`${API_BASE}/api/admin/leave-feature`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || "設定を読み込めませんでした");
        setLeaveFeature(Boolean(data.enabled));
        setLeaveStartedOn(data.startedOn || null);
      })
      .catch((err) => setLeaveFeatureError(err.message || "設定を読み込めませんでした"));
    async function loadMaintenance() {
      try {
        const response = await fetchApi(`${API_BASE}/api/admin/maintenance`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || "メンテナンス設定を読み込めませんでした");
        if (!cancelled) {
          setMaintenanceEnabled(Boolean(data.enabled));
          setMaintenanceError("");
        }
      } catch {
        if (!cancelled) {
          setMaintenanceError("メンテナンス設定を準備しています。自動で再確認します。");
          maintenanceRetry = window.setTimeout(loadMaintenance, 5000);
        }
      }
    }
    loadMaintenance();
    return () => {
      cancelled = true;
      if (maintenanceRetry) window.clearTimeout(maintenanceRetry);
    };
  }, [token, currentUser?.role]);

  async function changeMaintenance(enabled) {
    if (enabled && !window.confirm("メンテナンスモードを開始しますか？管理者以外はログイン・操作できなくなります。")) return;
    if (!enabled && !window.confirm("メンテナンスモードを終了し、全部員の利用を再開しますか？")) return;
    setMaintenanceLoading(true);
    setMaintenanceMessage("");
    setMaintenanceError("");
    try {
      const response = await fetchApi(`${API_BASE}/api/admin/maintenance`, {
        method: "PATCH",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "メンテナンス設定を変更できませんでした");
      setMaintenanceEnabled(Boolean(data.enabled));
      setMaintenanceMessage(data.message || "メンテナンス設定を変更しました。");
    } catch (err) {
      setMaintenanceError(err.message || "メンテナンス設定を変更できませんでした");
    } finally {
      setMaintenanceLoading(false);
    }
  }

  async function setLeaveFeatureEnabled(enabled) {
    setLeaveFeatureLoading(true);
    setLeaveFeatureMessage("");
    setLeaveFeatureError("");
    try {
      const response = await fetchApi(`${API_BASE}/api/admin/leave-feature`, {
        method: "PATCH",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "設定を変更できませんでした");
      setLeaveFeature(Boolean(data.enabled));
      setLeaveStartedOn(data.startedOn || null);
      setLeaveFeatureMessage(data.message || (enabled ? "休暇権利機能を開始しました。" : "休暇権利機能を停止しました。"));
      invalidateCache(token, "/api/home");
      invalidateCache(token, "/api/leave-credits");
    } catch (err) {
      setLeaveFeatureError(err.message || "設定を変更できませんでした");
    } finally {
      setLeaveFeatureLoading(false);
    }
  }

  const operationLinks = [
    ...(approvalRoles.has(currentUser?.role) ? [["承認する", "approvals"]] : []),
    ...(currentUser?.permissions?.canEditEvents ? [["予定を管理", "event-management"]] : []),
    ["出席未回答", "reminders"],
    ...(currentUser?.permissions?.canPublishAnnouncements ? [["お知らせ送信", "notices"]] : []),
    ...(currentUser?.role === "パートリーダー" ? [["パート連絡", "contact"]] : []),
    ...(currentUser?.role === "管理者" ? [["部員管理", "members"]] : []),
    ...(currentUser?.role === "管理者" ? [["公開設定", "publications"]] : []),
    ...(currentUser?.role === "管理者" ? [["欠席・遅刻一覧", "absence-report"]] : []),
    ...(currentUser?.role !== "パートリーダー" ? [["統計・先生ダッシュボード", "statistics"]] : []),
    ["表彰・ランキング", "ranking"],
  ];
  return (
    <>
      <ScreenIntro
        eyebrow="OPERATIONS"
        title="運営"
        text="承認、予定、お知らせ、部員管理をまとめて扱う運営用の入口です。"
      />
      {["部長", "副部長"].includes(currentUser?.role) && <LeadershipOverview
        data={leadershipStats}
        loading={leadershipStatsLoading}
        error={leadershipStatsError}
        setActive={setActive}
        role={currentUser.role}
      />}
      {["部長", "副部長"].includes(currentUser?.role) && <ScopedMemberAttendance token={token} title="全部員の出席管理" />}
      {currentUser?.role === "管理者" && <AdminDesktopOverview
        summary={summary}
        usageStats={usageStats}
        maintenanceEnabled={maintenanceEnabled}
        leaveFeature={leaveFeature}
        setActive={setActive}
      />}
      {currentUser?.role === "管理者" && (
        <Section title="役割別・閲覧専用アカウント">
          <div className="card preview-account-panel">
            <div className="item-note">各役割で見える画面を確認するための専用アカウントです。登録・編集・承認・削除はできません。</div>
            <div className="preview-account-table">
              <div className="preview-account-head"><span>確認する役割</span><span>ログインID</span><span>パスワード</span></div>
              <div><strong>部長</strong><code>0</code><code>0</code></div>
              <div><strong>副部長</strong><code>1</code><code>1</code></div>
              <div><strong>パートリーダー</strong><code>2</code><code>2</code><small>ホルンパート</small></div>
              <div><strong>先生</strong><code>3</code><code>3</code></div>
            </div>
            <div className="preview-account-note">確認するときは現在の管理者アカウントからログアウトし、上記の情報でログインしてください。</div>
          </div>
        </Section>
      )}
      {leaveFeatureError && <div className="card error-card">{leaveFeatureError}</div>}
      {leaveFeatureMessage && <div className="card success-card">{leaveFeatureMessage}</div>}
      {maintenanceError && <div className="card error-card">{maintenanceError}</div>}
      {maintenanceMessage && <div className="card success-card">{maintenanceMessage}</div>}
      {operationActionError && <div className="card error-card">{operationActionError}</div>}
      {operationActionMessage && <div className="card success-card">{operationActionMessage}</div>}
      {currentUser?.role === "管理者" && (
        <Section title="運用開始・データリセット">
          <div className="card">
            <div className="item-title">
              現在：{usageStats?.lifecycle?.phase === "trial" ? "試行期間" : usageStats?.lifecycle?.phase === "release" ? "本リリース" : "開始前"}
            </div>
            {usageStats?.lifecycle?.trialStartedOn && <div className="item-note">試行期間開始：{formatDateWithWeekday(usageStats.lifecycle.trialStartedOn)}</div>}
            {usageStats?.lifecycle?.releaseStartedOn && <div className="item-note">本リリース開始：{formatDateWithWeekday(usageStats.lifecycle.releaseStartedOn)}</div>}
            <div className="item-note card-action">部員・プロフィール・予定・関連システムは残し、出欠、お知らせ、通知、To Do、パート連絡、共有表、休暇利用履歴、ログイン履歴、公開統計をリセットします。</div>
            <div className="managed-event-actions card-action">
              <button className="small-button danger-button" disabled={operationActionLoading} onClick={() => startOperationPhase("trial")}>試行期間スタート</button>
              <button className="small-button danger-button" disabled={operationActionLoading} onClick={() => startOperationPhase("release")}>本リリーススタート</button>
            </div>
          </div>
        </Section>
      )}
      {currentUser?.role === "管理者" && (
        <Section title="新年度切替">
          <div className="card list-item admin-setting-item">
            <div>
              <div className="item-title">新年度へ切り替え</div>
              <div className="item-note">4年生と関連データを削除し、1〜3年生の学年を1つ上げます。</div>
            </div>
            <button className="small-button danger-button" disabled={operationActionLoading} onClick={advanceYear}>新年度へ切替</button>
          </div>
        </Section>
      )}
      {currentUser?.role === "管理者" && (
        <Section title="期間別の利用状況">
          <div className="card form-stack">
            <div className="grid two wide-grid">
              <label className="field-label">
                開始日
                <input className="input" type="date" value={usagePeriod.startDate} onChange={(event) => setUsagePeriod((current) => ({ ...current, startDate: event.target.value }))} />
              </label>
              <label className="field-label">
                終了日
                <input className="input" type="date" value={usagePeriod.endDate} onChange={(event) => setUsagePeriod((current) => ({ ...current, endDate: event.target.value }))} />
              </label>
            </div>
            <button className="primary-button" disabled={usageStatsLoading} onClick={() => loadUsageStats()}>
              {usageStatsLoading ? "集計中" : "この期間で集計"}
            </button>
            <button className="ghost-button" disabled={usageStatsLoading} onClick={loadFromSystemStart}>利用開始から今日まで</button>
          </div>
          {usageStatsError && <div className="card error-card">{usageStatsError}</div>}
          <div className="grid two wide-grid card-action">
            <Metric
              label="全体の出欠回答率"
              value={usageStats?.attendance?.rate == null ? "—" : `${usageStats.attendance.rate}%`}
              note={usageStats ? `${usageStats.attendance.responses}/${usageStats.attendance.opportunities}件・予定${usageStats.attendance.events}回` : "回答済み÷回答対象"}
            />
            <Metric
              label="期間内利用者数"
              value={usageStats ? `${usageStats.usage.activeUsers}人` : "—"}
              note="1回以上ログインした人数"
            />
            <Metric
              label="ログイン数"
              value={usageStats ? `${usageStats.usage.logins}回` : "—"}
              note="成功したログインの合計"
            />
            <Metric
              label="利用者率"
              value={usageStats?.usage?.activeUserRate == null ? "—" : `${usageStats.usage.activeUserRate}%`}
              note={usageStats ? `${usageStats.usage.activeUsers}/${usageStats.usage.currentMembers}人が利用` : "在籍部員の利用割合"}
            />
          </div>
          <div className="item-note">
            システム利用開始：{usageStats?.systemStartedOn ? formatDateWithWeekday(usageStats.systemStartedOn) : "確認中"}
            {usageStats?.daysInOperation ? `（運用${usageStats.daysInOperation}日目）` : ""}
          </div>
          <div className="item-note">ログイン履歴の詳細記録：{usageStats?.loginTrackingStartedOn ? `${formatDateWithWeekday(usageStats.loginTrackingStartedOn)}から` : "今回の公開後から"}</div>
        </Section>
      )}
      {currentUser?.role === "管理者" && (
        <Section title="企業・コンペ向け導入実績">
          <div className="grid two wide-grid">
            <Metric
              label="出欠回答のデジタル化"
              value={usageStats ? `${usageStats.attendance.responses}件` : "—"}
              note="システムで処理した回答"
            />
            <Metric
              label="欠席・遅刻等の申請"
              value={usageStats ? `${usageStats.workflow.requests}件` : "—"}
              note={usageStats ? `処理済み ${usageStats.workflow.processed}件` : "承認フローの利用数"}
            />
            <Metric
              label="申請処理率"
              value={usageStats?.workflow?.processingRate == null ? "—" : `${usageStats.workflow.processingRate}%`}
              note="承認または拒否まで完了"
            />
            <Metric
              label="平均承認時間"
              value={usageStats?.workflow?.averageApprovalHours == null ? "—" : `${usageStats.workflow.averageApprovalHours}時間`}
              note="申請から処理まで"
            />
            <Metric
              label="お知らせ配信"
              value={usageStats ? `${usageStats.engagement.announcements}件` : "—"}
              note="組織内の情報共有"
            />
            <Metric
              label="To Do活用"
              value={usageStats ? `${usageStats.engagement.completedTodos}/${usageStats.engagement.todos}件完了` : "—"}
              note="共同タスク管理"
            />
            <Metric
              label="パート連絡"
              value={usageStats ? `${usageStats.engagement.partMemos}件` : "—"}
              note="パート内の情報共有"
            />
            <Metric
              label="誕生日交流"
              value={usageStats ? `${usageStats.engagement.birthdayMessages}件` : "—"}
              note={usageStats ? `星リアクション ${usageStats.engagement.birthdayReactions}件` : "部員同士の交流"}
            />
          </div>
          <div className="item-note">上の期間指定と連動します。企業説明やコンペ資料には、期間と母数を一緒に記載してください。</div>
        </Section>
      )}
      {currentUser?.role === "管理者" && (
        <Section title="システムメンテナンス">
          <div className="card list-item admin-setting-item">
            <div>
              <div className="item-title">現在：{maintenanceEnabled === null ? "確認中" : maintenanceEnabled ? "メンテナンス中" : "通常稼働中"}</div>
              <div className="item-note">メンテナンス中は管理者だけがログイン・操作できます。点検が終わったら必ず利用を再開してください。</div>
            </div>
            {maintenanceEnabled ? (
              <button className="primary-button" disabled={maintenanceLoading} onClick={() => changeMaintenance(false)}>{maintenanceLoading ? "変更中" : "利用を再開"}</button>
            ) : (
              <button className="small-button danger-button" disabled={maintenanceLoading || maintenanceEnabled === null} onClick={() => changeMaintenance(true)}>{maintenanceLoading ? "変更中" : "メンテナンス開始"}</button>
            )}
          </div>
        </Section>
      )}
      {currentUser?.role === "管理者" && (
        <Section title="休暇権利機能">
          <div className="card list-item admin-setting-item">
            <div>
              <div className="item-title">現在：{leaveFeature === null ? "確認中" : leaveFeature ? "稼働中" : "停止中"}</div>
              {leaveFeature && leaveStartedOn && <div className="item-note">今回の開始日：{formatDateWithWeekday(leaveStartedOn)}</div>}
              <div className="item-note">開始日以降、その月のすべての練習・本番へ出席した部員だけに翌月1回付与します。欠席・遅刻・早退がある場合は付与されません。</div>
            </div>
            {leaveFeature ? (
              <button className="small-button danger-button" disabled={leaveFeatureLoading} onClick={() => setLeaveFeatureEnabled(false)}>
                {leaveFeatureLoading ? "変更中" : "ストップ"}
              </button>
            ) : (
              <button className="primary-button" disabled={leaveFeatureLoading || leaveFeature === null} onClick={() => setLeaveFeatureEnabled(true)}>
                {leaveFeatureLoading ? "変更中" : "スタート"}
              </button>
            )}
          </div>
        </Section>
      )}
      <Section title="優先して確認">
        <div className="ops-priority-grid">
          {approvalRoles.has(currentUser?.role) && <button className="card ops-priority-card" onClick={() => setActive("approvals")}>
            <span className="notice-badge important">承認</span>
            <strong>{summary.pendingApprovals === null ? "確認中" : `${summary.pendingApprovals}件の承認待ち`}</strong>
            <small>自分が担当する申請を確認する</small>
          </button>}
          <button className="card ops-priority-card" onClick={() => setActive("reminders")}>
            <span className="notice-badge">回答</span>
            <strong>{summary.unanswered === null ? "確認中" : `${summary.unanswered}人が未回答`}</strong>
            <small>{summary.reminderEvent ? `${formatDateWithWeekday(summary.reminderEvent.date)}の予定` : "次の予定を確認する"}</small>
          </button>
          {currentUser?.permissions?.canEditEvents && <button className="card ops-priority-card" onClick={() => setActive("event-management")}>
            <span className="notice-badge">予定</span>
            <strong>練習・本番を管理</strong>
            <small>登録、編集、削除を行う</small>
          </button>}
        </div>
      </Section>
      <Section title="運営メニュー">
        <div className="grid two wide-grid">
          <Metric
            label="承認待ち"
            value={summary.pendingApprovals === null ? "確認中" : `${summary.pendingApprovals}件`}
            note="出席申請・休暇申請"
          />
          <Metric
            label="未回答"
            value={summary.unanswered === null ? "確認中" : `${summary.unanswered}人`}
            note={summary.reminderEvent ? `${formatDateWithWeekday(summary.reminderEvent.date)}の予定` : "次の予定"}
          />
          <Metric
            label="部員数"
            value={summary.memberCount === null ? "確認中" : `${summary.memberCount}人`}
            note="在籍部員"
          />
        </div>
      </Section>
      <div className="grid two">
        {operationLinks.map(([label, target]) => (
          <button
            className={label === "承認する" ? "primary-button" : "ghost-button"}
            key={label}
            onClick={() => setActive(target)}
          >
            {label}
          </button>
        ))}
      </div>
    </>
  );
}

const screenMap = {
  home: HomeScreen,
  tasks: TasksScreen,
  calendar: CalendarScreen,
  attendance: AttendanceScreen,
  notices: NoticesScreen,
  contact: ContactScreen,
  ranking: RankingScreen,
  profile: ProfileScreen,
  ops: OpsScreen,
  approvals: ApprovalsScreen,
  members: MembersScreen,
  statistics: StatisticsScreen,
  reminders: RemindersScreen,
  publications: PublicationsScreen,
  "absence-report": AbsenceReportScreen,
  "event-management": EventManagementScreen,
};

function SignIn({ onLogin }) {
  const [mode, setMode] = useState("login");
  const [studentId, setStudentId] = useState("");
  const [pin, setPin] = useState("");
  const [showPinSetup, setShowPinSetup] = useState(false);
  const [pinSetup, setPinSetup] = useState({ studentId: "", name: "", pin: "", confirmPin: "" });
  const [rememberLogin, setRememberLogin] = useState(false);
  const [hasSavedLogin, setHasSavedLogin] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [apiStatus, setApiStatus] = useState("checking");
  const [registration, setRegistration] = useState({ studentId: "", name: "", pin: "", confirmPin: "" });
  const [registrationMessage, setRegistrationMessage] = useState("");

  useEffect(() => {
    window.localStorage.removeItem("bandattend_saved_session");
    try {
      const saved = JSON.parse(window.localStorage.getItem(SAVED_LOGIN_KEY) || "null");
      if (saved?.studentId) {
        setStudentId(saved.studentId);
        setPin(saved.pin || "");
        setRememberLogin(true);
        setHasSavedLogin(true);
        if (saved?.name) {
          setPinSetup({ studentId: saved.studentId, name: saved.name, pin: "", confirmPin: "" });
          setShowPinSetup(true);
        }
      }
    } catch {
      window.localStorage.removeItem(SAVED_LOGIN_KEY);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const noticeTimer = setTimeout(() => {
      if (!cancelled) setApiStatus("waking");
    }, API_WAKEUP_NOTICE_DELAY);

    const earlyWarmup = API_BASE === "" ? window.__bandAttendApiWarmup : null;
    const warmupRequest = earlyWarmup
      || fetchApi(`${API_BASE}/api/health?warm=${Date.now()}`, { cache: "no-store" });

    warmupRequest
      .then((response) => {
        if (!response.ok) throw new Error("API wakeup failed");
        if (!cancelled) setApiStatus("ready");
      })
      .catch(() => {
        if (!cancelled) setApiStatus("slow");
      })
      .finally(() => clearTimeout(noticeTimer));

    return () => {
      cancelled = true;
      clearTimeout(noticeTimer);
    };
  }, []);

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");

    const compactStudentId = studentId.trim();
    const isPreviewLogin = ["0", "1", "2", "3"].includes(compactStudentId) && pin === compactStudentId;
    if (!compactStudentId || !pin) {
      setError("ログインIDとパスワードを入力してください");
      return;
    }
    if (!isPreviewLogin && !(pin === "0" || /^\d{4}$/.test(pin))) {
      setError("ログインIDまたはパスワードが違います");
      return;
    }

    setLoading(true);

    try {
      const response = await fetchApi(`${API_BASE}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({ studentId: compactStudentId, pin }),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        if (response.status === 409 && pin === "0" && body.detail === "初回暗証番号設定が必要です") {
          setShowPinSetup(true);
          setPinSetup({ studentId: compactStudentId, name: "", pin: "", confirmPin: "" });
          setError("本人確認のため氏名を入力し、新しい4桁の暗証番号を設定してください");
          return;
        }
        if (response.status === 401) {
          throw new Error("ログインIDまたはパスワードが違います");
        }
        throw new Error(typeof body.detail === "string" ? body.detail : "ログインに失敗しました");
      }

      const data = await response.json();
      if (rememberLogin) {
        window.localStorage.setItem(SAVED_LOGIN_KEY, JSON.stringify({
          studentId: compactStudentId,
          pin,
        }));
      } else {
        window.localStorage.removeItem(SAVED_LOGIN_KEY);
      }
      onLogin(data);
    } catch (err) {
      setError(err instanceof TypeError ? "ログインに失敗しました" : (err.message || "ログインに失敗しました"));
    } finally {
      setLoading(false);
    }
  }

  async function handleDemoRoleLogin(account) {
    setError("");
    setLoading(account.label);
    try {
      const response = await fetchApi(`${API_BASE}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({ studentId: account.studentId, pin: account.pin }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "ログインに失敗しました");
      onLogin(body);
    } catch (err) {
      setError(err instanceof TypeError ? "ログインに失敗しました" : (err.message || "ログインに失敗しました"));
    } finally {
      setLoading(false);
    }
  }

  async function handlePinSetup(event) {
    event.preventDefault();
    setError("");
    if (!pinSetup.studentId.trim() || !pinSetup.name.trim()) return setError("学籍番号と氏名を入力してください");
    if (!/^\d{4}$/.test(pinSetup.pin)) return setError("暗証番号は4桁の数字で入力してください");
    if (pinSetup.pin !== pinSetup.confirmPin) return setError("確認用の暗証番号が一致しません");
    setLoading(true);
    try {
      const response = await fetchApi(`${API_BASE}/api/auth/setup-pin`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({ studentId: pinSetup.studentId.trim(), name: pinSetup.name.trim(), pin: pinSetup.pin }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "暗証番号を設定できませんでした");
      if (rememberLogin) {
        window.localStorage.setItem(SAVED_LOGIN_KEY, JSON.stringify({ studentId: pinSetup.studentId.trim(), pin: pinSetup.pin }));
      } else {
        window.localStorage.removeItem(SAVED_LOGIN_KEY);
      }
      onLogin(body);
    } catch (err) {
      setError(err.message || "暗証番号を設定できませんでした");
    } finally {
      setLoading(false);
    }
  }

  async function handleRegistration(event) {
    event.preventDefault();
    setError("");
    setRegistrationMessage("");
    if (!registration.studentId.trim() || !registration.name.trim()) {
      setError("学籍番号と氏名を入力してください");
      return;
    }
    if (!/^\d{4}$/.test(registration.pin)) return setError("暗証番号は4桁の数字で入力してください");
    if (registration.pin !== registration.confirmPin) return setError("確認用の暗証番号が一致しません");
    setLoading(true);
    try {
      const response = await fetchApi(`${API_BASE}/api/member-registration-requests`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(registration),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = typeof body.detail === "string" ? body.detail : "登録申請を送信できませんでした。時間をおいてもう一度お試しください。";
        throw new Error(detail);
      }
      setRegistrationMessage("申請完了しました。管理者の承認後にログインできます。");
      setRegistration({ studentId: "", name: "", pin: "", confirmPin: "" });
    } catch (err) {
      setError(err.message || "登録申請を送信できませんでした");
    } finally {
      setLoading(false);
    }
  }

  function forgetSavedLogin() {
    window.localStorage.removeItem(SAVED_LOGIN_KEY);
    setRememberLogin(false);
    setHasSavedLogin(false);
    setStudentId("");
    setPin("");
    setError("");
  }

  return (
    <main className="signin">
      <div className="signin-card">
        <h1 className="signin-title">BandAttend</h1>
        <p className="signin-copy">吹奏楽部の予定、出席、連絡をひとつに。</p>
        {isPortfolioDemo ? <div className="demo-role-login">
          <div className="demo-role-heading">見たい役割を選んでください</div>
          <p className="demo-role-copy">入力不要で、各役割の画面を体験できます。</p>
          <div className="demo-role-grid">
            {portfolioDemoRoles.map((account) => <button
              type="button"
              className="demo-role-button"
              key={account.label}
              disabled={Boolean(loading)}
              onClick={() => handleDemoRoleLogin(account)}
            >
              <span>{account.label}</span>
              <small>{loading === account.label ? "接続中です…" : account.description}</small>
            </button>)}
          </div>
          {loading && <div className="signin-status signin-connecting"><span className="loading-spinner" aria-hidden="true" />接続中です</div>}
          {error && <p className="form-error login-field-error">{error}</p>}
          <div className="demo-login-notice"><strong>実際の運用では</strong><span>本人のログインID（学籍番号）とパスワードの入力が必要です。この選択式ログインは、作品を安全かつ簡単に体験するためのデモ専用機能です。</span></div>
        </div> : <>
        <div className="signin-tabs">
          <button type="button" className={mode === "login" ? "active" : ""} onClick={() => { setMode("login"); setShowPinSetup(false); setError(""); }}>ログイン</button>
          <button type="button" className={mode === "register" ? "active" : ""} onClick={() => { setMode("register"); setShowPinSetup(false); setError(""); }}>部員登録を申請</button>
        </div>
        {mode === "login" && !showPinSetup ? <form className="form-stack" onSubmit={handleSubmit}>
          <input className="input" placeholder="ログインID（学籍番号）" value={studentId} autoComplete="username" onChange={(event) => { setStudentId(event.target.value); setError(""); }} />
          <input className="input" type="password" inputMode="numeric" maxLength={4} placeholder="パスワード（通常は4桁・初回は0）" value={pin} autoComplete="current-password" onChange={(event) => { setPin(event.target.value.replace(/\D/g, "").slice(0, 4)); setError(""); }} />
          {error && <p className="form-error login-field-error">{error}</p>}
          <label className="remember-login">
            <input type="checkbox" checked={rememberLogin} onChange={(event) => setRememberLogin(event.target.checked)} />
            <span>このスマホに学籍番号と暗証番号を保存する</span>
          </label>
          {rememberLogin && <div className="item-note">自分専用のスマホでのみ使用してください。</div>}
          <button className="primary-button" disabled={loading} aria-busy={loading}>
            {loading ? <span className="login-loading"><span className="loading-spinner" aria-hidden="true" />接続中です</span> : "ログイン"}
          </button>
          <button type="button" className="forget-login-button" onClick={() => { setShowPinSetup(true); setPinSetup({ studentId, name: "", pin: "", confirmPin: "" }); setError(""); }}>初回暗証番号設定・リセット後の再設定</button>
        </form> : mode === "login" ? <form className="form-stack pin-setup-form" onSubmit={handlePinSetup}>
          <div className="item-title">自分の暗証番号を設定</div>
          <div className="item-note">管理者が登録した氏名で本人確認し、自分だけが使用する新しい4桁の暗証番号を設定します。</div>
          <input className="input" required placeholder="学籍番号" value={pinSetup.studentId} onChange={(event) => setPinSetup({...pinSetup, studentId:event.target.value})} />
          <input className="input" required placeholder="氏名" value={pinSetup.name} onChange={(event) => setPinSetup({...pinSetup, name:event.target.value})} />
          <input className="input" required type="password" inputMode="numeric" maxLength={4} placeholder="4桁の暗証番号" value={pinSetup.pin} onChange={(event) => setPinSetup({...pinSetup, pin:event.target.value.replace(/\D/g, "").slice(0, 4)})} />
          <input className="input" required type="password" inputMode="numeric" maxLength={4} placeholder="暗証番号をもう一度入力" value={pinSetup.confirmPin} onChange={(event) => setPinSetup({...pinSetup, confirmPin:event.target.value.replace(/\D/g, "").slice(0, 4)})} />
          <label className="remember-login">
            <input type="checkbox" checked={rememberLogin} onChange={(event) => setRememberLogin(event.target.checked)} />
            <span>このスマホに学籍番号と暗証番号を保存する</span>
          </label>
          {rememberLogin && <div className="item-note">自分専用のスマホでのみ使用してください。</div>}
          <button className="primary-button" disabled={loading}>{loading ? "設定中" : "設定してログイン"}</button>
          <button type="button" className="ghost-button" onClick={() => { setShowPinSetup(false); setError(""); }}>通常ログインに戻る</button>
        </form> : <form className="form-stack registration-form" onSubmit={handleRegistration}>
          <input className="input" required placeholder="学籍番号" value={registration.studentId} onChange={(event) => setRegistration({...registration, studentId:event.target.value})} />
          <input className="input" required placeholder="氏名" value={registration.name} onChange={(event) => setRegistration({...registration, name:event.target.value})} />
          <input className="input" required type="password" inputMode="numeric" maxLength={4} placeholder="4桁の暗証番号" value={registration.pin} onChange={(event) => setRegistration({...registration, pin:event.target.value.replace(/\D/g, "").slice(0, 4)})} />
          <input className="input" required type="password" inputMode="numeric" maxLength={4} placeholder="暗証番号をもう一度入力" value={registration.confirmPin} onChange={(event) => setRegistration({...registration, confirmPin:event.target.value.replace(/\D/g, "").slice(0, 4)})} />
          <button className="primary-button" disabled={loading}>{loading ? "送信中" : "登録を申請"}</button>
        </form>}
        {mode === "login" && !showPinSetup && hasSavedLogin && <button type="button" className="forget-login-button" onClick={forgetSavedLogin}>保存したログイン情報を消す</button>}
        {apiStatus === "waking" && <p className="signin-status signin-connecting"><span className="loading-spinner" aria-hidden="true" />接続中です</p>}
        {apiStatus === "slow" && <p className="signin-status">サーバー起動に時間がかかっています。ログインボタンを押した後も少し待つ場合があります。</p>}
        {error && (mode !== "login" || showPinSetup) && <p className="form-error">{error}</p>}
        {registrationMessage && <p className="signin-success">{registrationMessage}</p>}
        <p className="item-note" style={{ textAlign: "center", marginTop: 24 }}>
          {mode === "login" ? "学籍番号と暗証番号で安全にログインします" : "申請後、管理者の承認をお待ちください"}
        </p>
        </>}
      </div>
    </main>
  );
}

export default function App() {
  const [active, setActive] = useState("home");
  const [history, setHistory] = useState([]);
  const [auth, setAuth] = useState(null);
  const [unreadNotices, setUnreadNotices] = useState(0);
  const [showFirstGuide, setShowFirstGuide] = useState(false);
  const [savingGuide, setSavingGuide] = useState(false);
  const [privacyAgreed, setPrivacyAgreed] = useState(false);
  const [privacySaveError, setPrivacySaveError] = useState("");
  const [savingPrivacyPurpose, setSavingPrivacyPurpose] = useState(false);
  const [showBirthdayCelebration, setShowBirthdayCelebration] = useState(false);
  const [maintenanceActive, setMaintenanceActive] = useState(false);
  const ActiveScreen = useMemo(() => screenMap[active] || HomeScreen, [active]);
  const visibleNav = useMemo(() => navForUser(auth?.user), [auth]);
  const operationTitles = {
    "event-management": "予定を管理",
    approvals: "出欠承認",
    members: auth?.user?.role === "管理者" ? "部員管理" : "部員一覧",
    statistics: "統計",
    reminders: "出席未回答",
    publications: "公開設定",
    "absence-report": "欠席・遅刻一覧",
  };
  const title = operationTitles[active] || visibleNav.find((item) => item.id === active)?.label || "BandAttend";

  useEffect(() => {
    if (!auth?.token || !auth?.user?.hasSeenPrivacy) {
      setUnreadNotices(0);
      return;
    }
    let cancelled = false;
    async function refreshUnreadNotices() {
      try {
        const headers = { Authorization: `Bearer ${auth.token}` };
        const [announcementResponse, notificationResponse] = await Promise.all([
          fetchApi(`${API_BASE}/api/announcements?filter=unread`, { headers }),
          fetchApi(`${API_BASE}/api/notifications?filter=unread`, { headers }),
        ]);
        if (!announcementResponse.ok || !notificationResponse.ok) return;
        const [announcementData, notificationData] = await Promise.all([
          announcementResponse.json(),
          notificationResponse.json(),
        ]);
        if (!cancelled) {
          setUnreadNotices(
            (announcementData.announcements || []).length
            + (notificationData.notifications || []).length,
          );
        }
      } catch {
        // Keep the last known badge state while temporarily offline.
      }
    }
    refreshUnreadNotices();
    const timer = window.setInterval(refreshUnreadNotices, 60000);
    const refreshOnFocus = () => refreshUnreadNotices();
    window.addEventListener("focus", refreshOnFocus);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener("focus", refreshOnFocus);
    };
  }, [auth?.token, auth?.user?.hasSeenPrivacy]);

  useEffect(() => {
    if (!auth?.token || auth?.user?.role === "管理者") {
      setMaintenanceActive(false);
      return;
    }
    let cancelled = false;
    async function checkMaintenance() {
      const response = await fetchApi(`${API_BASE}/api/maintenance-status`).catch(() => null);
      if (!response?.ok) return;
      const data = await response.json().catch(() => ({}));
      if (!cancelled) setMaintenanceActive(Boolean(data.enabled));
    }
    checkMaintenance();
    const timer = window.setInterval(checkMaintenance, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [auth?.token, auth?.user?.role]);

  useEffect(() => {
    setShowFirstGuide(Boolean(auth?.user && auth.user.hasSeenPrivacy && !auth.user.hasSeenGuide));
  }, [auth?.user?.id, auth?.user?.hasSeenGuide, auth?.user?.hasSeenPrivacy]);

  useEffect(() => {
    setPrivacyAgreed(false);
    setPrivacySaveError("");
  }, [auth?.user?.id]);

  useEffect(() => {
    setShowBirthdayCelebration(Boolean(auth?.user?.showBirthdayCelebration));
  }, [auth?.user?.id, auth?.user?.showBirthdayCelebration]);

  async function finishPrivacyPurpose() {
    if (!auth?.token || !privacyAgreed) return;
    setSavingPrivacyPurpose(true);
    setPrivacySaveError("");
    const response = await fetchApi(`${API_BASE}/api/profile/privacy-seen`, {
      method: "POST",
      headers: { Authorization: `Bearer ${auth.token}` },
    }).catch(() => null);
    if (response?.ok) {
      setAuth((current) => ({ ...current, user: { ...current.user, hasSeenPrivacy: true } }));
    } else {
      setPrivacySaveError("同意内容を保存できませんでした。通信状態を確認して、もう一度お試しください。");
    }
    setSavingPrivacyPurpose(false);
  }

  function declinePrivacyPurpose() {
    window.localStorage.removeItem(SAVED_LOGIN_KEY);
    setPrivacyAgreed(false);
    setPrivacySaveError("");
    setAuth(null);
  }

  async function finishFirstGuide() {
    if (!auth?.token) return;
    setSavingGuide(true);
    const response = await fetchApi(`${API_BASE}/api/profile/guide-seen`, {
      method: "POST",
      headers: { Authorization: `Bearer ${auth.token}` },
    }).catch(() => null);
    if (response?.ok) {
      setAuth((current) => ({ ...current, user: { ...current.user, hasSeenGuide: true } }));
      setShowFirstGuide(false);
    }
    setSavingGuide(false);
  }

  function updateUser(user) {
    setAuth((current) => ({ ...current, user }));
  }

  function navigate(target) {
    if (target === active) return;
    setHistory((current) => [...current, active]);
    setActive(target);
  }

  function goBack() {
    setHistory((current) => {
      if (current.length === 0) return current;
      setActive(current[current.length - 1]);
      return current.slice(0, -1);
    });
  }

  if (!auth) {
    return <SignIn onLogin={setAuth} />;
  }

  if (maintenanceActive && auth.user.role !== "管理者") {
    return <MaintenanceScreen />;
  }

  if (!auth.user.hasSeenPrivacy) {
    return <main className="signin privacy-consent-page">
      <div className="signin-card privacy-consent-card" role="dialog" aria-modal="true" aria-labelledby="privacy-purpose-title">
        <div className="intro-eyebrow">PRIVACY</div>
        <h1 id="privacy-purpose-title" className="privacy-consent-title">個人情報の取り扱いへの同意</h1>
        <p className="item-note">BandAttendを利用する前に、個人情報の取り扱いを確認し、同意してください。</p>
        <PrivacyPurposeContent />
        <label className="privacy-consent-check">
          <input type="checkbox" checked={privacyAgreed} onChange={(event) => setPrivacyAgreed(event.target.checked)} />
          <span>上記の個人情報の取り扱いに同意します</span>
        </label>
        {privacySaveError && <p className="form-error">{privacySaveError}</p>}
        <button className="primary-button guide-start-button" onClick={finishPrivacyPurpose} disabled={!privacyAgreed || savingPrivacyPurpose} aria-busy={savingPrivacyPurpose}>
          {savingPrivacyPurpose ? <span className="login-loading"><span className="loading-spinner" aria-hidden="true" />保存中です</span> : "同意して利用を開始する"}
        </button>
        <button type="button" className="ghost-button privacy-decline-button" onClick={declinePrivacyPurpose} disabled={savingPrivacyPurpose}>同意せずログアウトする</button>
      </div>
    </main>;
  }

  return (
    <main className="app">
      <Sidebar active={active} setActive={navigate} visibleNav={visibleNav} />
      <div className={`phone ${auth.user.role === "管理者" ? `admin-workspace screen-${active}` : ""}`}>
        <TopBar title={title} user={auth.user} canGoBack={history.length > 0} onBack={goBack} />
        {auth.user.readOnly && (
          <div className="read-only-banner" role="status">
            閲覧専用モード：登録・編集・承認・削除はできません
          </div>
        )}
        <ActiveScreen setActive={navigate} currentUser={auth.user} token={auth.token} onUserUpdate={updateUser} onUnreadNoticesChange={setUnreadNotices} />
      </div>
      <BottomNav active={active} setActive={navigate} visibleNav={visibleNav} unreadNotices={unreadNotices} currentUser={auth.user} />
      {showBirthdayCelebration && !showFirstGuide && (
        <BirthdayCelebration name={auth.user.name} onClose={() => setShowBirthdayCelebration(false)} />
      )}
      {showFirstGuide && <div className="guide-overlay" role="dialog" aria-modal="true" aria-labelledby="first-guide-title">
        <div className="guide-modal">
          <div className="intro-eyebrow">WELCOME</div>
          <h2 id="first-guide-title">BandAttendへようこそ</h2>
          <p className="item-note">最初に、システムでできることと基本的な使い方を確認してください。</p>
          <SystemGuideContent />
          <button className="primary-button guide-start-button" onClick={finishFirstGuide} disabled={savingGuide}>
            {savingGuide ? "保存中" : "使い始める"}
          </button>
        </div>
      </div>}
    </main>
  );
}
