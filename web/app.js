/* Kabi Mini App. Спека: docs/services/miniapp.md
 *
 * Тонкий клиент: рисует то, что отдал /api/v1, и шлёт обратно реакции.
 * Никаких решений о подборе здесь нет — они на сервере.
 */

(() => {
  "use strict";

  const tg = window.Telegram && window.Telegram.WebApp;

  const TABS = [
    { id: "jobs", icon: "search", label: "Вакансии", title: "Вакансии", kind: "feed" },
    { id: "pitch", icon: "mic", label: "СМИ", title: "СМИ и подкасты", kind: "feed" },
    { id: "talks", icon: "stage", label: "Конфы", title: "Конференции", kind: "feed" },
    { id: "saved", icon: "bookmark", label: "Избранное", title: "Избранное", kind: "saved" },
    { id: "profile", icon: "user", label: "Профиль", title: "Профиль", kind: "profile" },
  ];

  const EMPTY_HINTS = {
    jobs: ["inbox", "Свежих вакансий нет", "Нажми «Обновить» — схожу в источники прямо сейчас."],
    pitch: ["mic", "Пока нет СМИ и подкастов", "Обнови или добавь темы экспертности в чате."],
    talks: ["stage", "Нет конференций со сроком подачи", "Нажми «Обновить» — поищу новые."],
    saved: ["bookmark", "В избранном пусто", "Жми «В избранное» на карточке — вернёшься сюда."],
  };

  const state = {
    tab: "jobs",
    data: {},
    loading: {},
    me: null,
  };

  const el = {
    app: document.getElementById("app"),
    gate: document.getElementById("gate"),
    gateText: document.getElementById("gate-text"),
    screen: document.getElementById("screen"),
    title: document.getElementById("screen-title"),
    tabbar: document.getElementById("tabbar"),
    refresh: document.getElementById("refresh-btn"),
    refreshIcon: document.getElementById("refresh-icon"),
    sheet: document.getElementById("sheet"),
    sheetTitle: document.getElementById("sheet-title"),
    sheetBody: document.getElementById("sheet-body"),
    sheetCopy: document.getElementById("sheet-copy"),
    sheetClose: document.getElementById("sheet-close"),
    toast: document.getElementById("toast"),
  };

  /* ---------------- helpers ---------------- */

  function haptic(kind, style) {
    const h = tg && tg.HapticFeedback;
    if (!h) return;
    try {
      if (kind === "impact") h.impactOccurred(style || "light");
      else if (kind === "notify") h.notificationOccurred(style || "success");
      else h.selectionChanged();
    } catch (_) {
      /* haptics недоступны на десктопе — не мешаем */
    }
  }

  let toastTimer = null;
  function toast(message) {
    el.toast.textContent = message;
    el.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      el.toast.hidden = true;
    }, 2600);
  }

  function node(tag, className, text) {
    const n = document.createElement(tag);
    if (className) n.className = className;
    if (text != null) n.textContent = text;
    return n;
  }

  /* Монохромные штриховые иконки: наследуют currentColor и тему Telegram.
     Только <path>, чтобы обойтись одним хелпером. */
  const SVG_NS = "http://www.w3.org/2000/svg";

  const ICONS = {
    search: ["M19 11a8 8 0 1 1-16 0 8 8 0 0 1 16 0", "M21 21l-4.35-4.35"],
    mic: [
      "M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z",
      "M19 10v1a7 7 0 0 1-14 0v-1",
      "M12 18v4",
      "M8 22h8",
    ],
    stage: ["M3 4h18v12H3z", "M12 16v5", "M8 21h8"],
    bookmark: ["M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"],
    user: ["M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2", "M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0"],
    like: [
      "M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3",
      "M7 11l4-9a3 3 0 0 1 3 3v4h5.28a2 2 0 0 1 2 2.3l-1.38 9a2 2 0 0 1-2 1.7H7z",
    ],
    dislike: [
      "M17 2h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3",
      "M17 13l-4 9a3 3 0 0 1-3-3v-4H4.72a2 2 0 0 1-2-2.3l1.38-9a2 2 0 0 1 2-1.7H17z",
    ],
    hide: [
      "M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94",
      "M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19",
      "M14.12 14.12a3 3 0 1 1-4.24-4.24",
      "M1 1l22 22",
    ],
    draft: ["M12 20h9", "M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"],
    refresh: [
      "M21 4v6h-6",
      "M3 20v-6h6",
      "M3.51 9a9 9 0 0 1 14.85-3.36L21 9",
      "M20.49 15a9 9 0 0 1-14.85 3.36L3 15",
    ],
    inbox: [
      "M22 12h-6l-2 3h-4l-2-3H2",
      "M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z",
    ],
    alert: [
      "M12 9v4",
      "M12 17h.01",
      "M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z",
    ],
    clipboard: [
      "M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2",
      "M9 2h6v4H9z",
    ],
    check: ["M20 6L9 17l-5-5"],
    clock: ["M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0", "M12 7v5l3 2"],
    file: ["M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z", "M14 2v6h6"],
    link: [
      "M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71",
      "M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71",
    ],
    bell: ["M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9", "M13.73 21a2 2 0 0 1-3.46 0"],
    trash: [
      "M3 6h18",
      "M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6",
      "M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2",
      "M10 11v6",
      "M14 11v6",
    ],
    chevron: ["M9 18l6-6-6-6"],
  };

  function icon(name, size) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.8");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    if (size) {
      svg.style.width = `${size}px`;
      svg.style.height = `${size}px`;
    }
    (ICONS[name] || []).forEach((d) => {
      const path = document.createElementNS(SVG_NS, "path");
      path.setAttribute("d", d);
      svg.appendChild(path);
    });
    return svg;
  }

  function formatDeadline(iso) {
    if (!iso) return null;
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    const days = Math.ceil((d - new Date()) / 86400000);
    const date = d.toLocaleDateString("ru-RU", { day: "2-digit", month: "short" });
    if (days < 0) return `Дедлайн прошёл · ${date}`;
    if (days === 0) return `Дедлайн сегодня · ${date}`;
    if (days <= 7) return `Дедлайн через ${days} дн. · ${date}`;
    return `Дедлайн ${date}`;
  }

  /* ---------------- api ---------------- */

  class ApiError extends Error {
    constructor(status, code, message) {
      super(message);
      this.status = status;
      this.code = code;
    }
  }

  async function api(path, options) {
    const opts = options || {};
    const headers = { Authorization: `tma ${tg.initData}` };
    if (opts.body) headers["Content-Type"] = "application/json";

    let response;
    try {
      response = await fetch(path, {
        method: opts.method || "GET",
        headers,
        body: opts.body ? JSON.stringify(opts.body) : undefined,
      });
    } catch (_) {
      throw new ApiError(0, "network", "Нет связи с сервером.");
    }

    let payload = null;
    try {
      payload = await response.json();
    } catch (_) {
      payload = null;
    }

    if (!response.ok) {
      const code = (payload && payload.code) || `http_${response.status}`;
      const message = (payload && payload.message) || "Что-то пошло не так.";
      throw new ApiError(response.status, code, message);
    }
    return payload;
  }

  /* ---------------- cards ---------------- */

  function buildCard(card, context) {
    const root = node("article", "card");
    root.dataset.matchId = card.match_id;

    if (card.type === "talk") root.appendChild(node("div", "card__badge", "Выступление"));

    root.appendChild(node("h3", "card__title", card.title));
    if (card.org) root.appendChild(node("div", "card__org", card.org));

    const chips = node("div", "chips");
    if (card.salary) chips.appendChild(node("span", "chip chip--accent", card.salary));
    if (card.location) chips.appendChild(node("span", "chip", card.location));
    if (card.remote) chips.appendChild(node("span", "chip", "удалённо"));
    const deadline = formatDeadline(card.deadline);
    if (deadline) chips.appendChild(node("span", "chip chip--warn", deadline));
    if (card.source) chips.appendChild(node("span", "chip", card.source));
    if (chips.childElementCount) root.appendChild(chips);

    if (card.summary) {
      const block = node("p", "card__block");
      block.appendChild(node("b", null, "Суть: "));
      block.appendChild(document.createTextNode(card.summary));
      root.appendChild(block);
    }

    if (card.reason) {
      const reason = node("div", "card__reason");
      reason.appendChild(node("b", null, "Почему ты: "));
      reason.appendChild(document.createTextNode(card.reason));
      root.appendChild(reason);
    }

    if (card.url) {
      const link = node("a", "card__link", card.link_label || "Открыть →");
      link.href = card.url;
      link.addEventListener("click", (event) => {
        event.preventDefault();
        haptic("impact");
        if (tg && tg.openLink) tg.openLink(card.url);
        else window.open(card.url, "_blank", "noopener");
      });
      root.appendChild(link);
    }

    root.appendChild(buildActions(card, root, context));
    return root;
  }

  function actionButton(iconName, label, className) {
    const button = node("button", `act${className ? " " + className : ""}`);
    button.type = "button";
    button.appendChild(icon(iconName));
    button.appendChild(node("span", "act__label", label));
    return button;
  }

  function setActionLabel(button, label) {
    button.querySelector(".act__label").textContent = label;
  }

  function buildActions(card, root, context) {
    const actions = node("div", "card__actions");
    const saved = { value: Boolean(card.saved) };

    const like = actionButton("like", "Интересно");
    const dislike = actionButton("dislike", "Мимо");
    const save = actionButton(
      "bookmark",
      saved.value ? "В избранном" : "В избранное",
      saved.value ? "is-on" : ""
    );
    const hide = actionButton("hide", "Скрыть");
    const draft = actionButton(
      "draft",
      card.type === "talk" ? "Черновик заявки" : "Сопроводительное письмо",
      "act--wide"
    );

    async function react(reaction, button) {
      const buttons = [like, dislike, save, hide];
      buttons.forEach((b) => (b.disabled = true));
      try {
        const result = await api(`/api/v1/matches/${card.match_id}/reaction`, {
          method: "POST",
          body: { reaction },
        });
        haptic("notify", "success");
        onReaction(result.effect, result.learned);
      } catch (error) {
        haptic("notify", "error");
        toast(error.message);
        if (error.status === 403 || error.status === 404) root.classList.add("is-gone");
      } finally {
        buttons.forEach((b) => (b.disabled = false));
        if (button) button.blur();
      }
    }

    function onReaction(effect, learned) {
      if (effect === "saved" || effect === "unsaved") {
        saved.value = effect === "saved";
        save.classList.toggle("is-on", saved.value);
        setActionLabel(save, saved.value ? "В избранном" : "В избранное");
        if (context.kind === "saved" && !saved.value) {
          removeCard(root);
          toast("Убрал из избранного");
        } else {
          toast(saved.value ? "Добавил в избранное" : "Убрал из избранного");
        }
        refreshSavedBadge(saved.value ? 1 : -1);
        return;
      }
      if (effect === "hidden") {
        removeCard(root);
        toast("Скрыл — больше не покажу");
        return;
      }
      const base = effect === "up" ? "Буду искать похожее" : "Меньше такого";
      toast(learned ? `${base}. Учёл для следующих подборок.` : base);
      removeCard(root);
    }

    like.addEventListener("click", () => react("up", like));
    dislike.addEventListener("click", () => react("down", dislike));
    save.addEventListener("click", () => react(saved.value ? "unsave" : "save", save));
    hide.addEventListener("click", () => react("hide", hide));
    draft.addEventListener("click", () => requestDraft(card, draft));

    actions.append(like, dislike, save, hide, draft);
    return actions;
  }

  function removeCard(root) {
    const data = state.data[state.tab];
    if (data && data.items) {
      data.items = data.items.filter((item) => item.match_id !== root.dataset.matchId);
    }
    root.style.transition = "opacity .2s ease, transform .2s ease";
    root.style.opacity = "0";
    root.style.transform = "scale(.97)";
    setTimeout(() => {
      const parent = root.parentElement;
      root.remove();
      if (parent && !parent.querySelector(".card")) render();
    }, 200);
  }

  async function requestDraft(card, button) {
    const label = button.querySelector(".act__label").textContent;
    button.disabled = true;
    setActionLabel(button, "Пишу черновик…");
    try {
      const result = await api(`/api/v1/matches/${card.match_id}/draft`, { method: "POST" });
      haptic("notify", "success");
      openSheet(
        result.kind === "talk_pitch" ? "Черновик заявки" : "Сопроводительное письмо",
        result.text
      );
    } catch (error) {
      haptic("notify", "error");
      toast(error.message);
    } finally {
      button.disabled = false;
      setActionLabel(button, label);
    }
  }

  /* ---------------- sheet ---------------- */

  function openSheet(title, text) {
    el.sheetTitle.textContent = title;
    el.sheetBody.textContent = text;
    el.sheet.hidden = false;
    el.sheetCopy.onclick = async () => {
      try {
        await navigator.clipboard.writeText(text);
        haptic("notify", "success");
        toast("Скопировал — проверь и отправь сам");
      } catch (_) {
        toast("Не смог скопировать — выдели текст вручную");
      }
    };
  }

  function closeSheet() {
    el.sheet.hidden = true;
  }

  /* ---------------- screens ---------------- */

  function skeleton(count) {
    const wrap = document.createDocumentFragment();
    for (let i = 0; i < count; i += 1) {
      const box = node("div", "skeleton");
      box.appendChild(node("div", "skeleton__line")).style.width = "62%";
      box.appendChild(node("div", "skeleton__line")).style.width = "40%";
      box.appendChild(node("div", "skeleton__line")).style.width = "100%";
      box.appendChild(node("div", "skeleton__line")).style.width = "84%";
      wrap.appendChild(box);
    }
    return wrap;
  }

  function emptyState(iconName, title, text, action) {
    const box = node("div", "empty");
    box.appendChild(icon(iconName, 34));
    box.appendChild(node("div", "empty__title", title));
    if (text) box.appendChild(node("div", null, text));
    if (action) {
      const button = node("button", "btn btn--ghost", action.label);
      button.addEventListener("click", action.onClick);
      box.appendChild(button);
    }
    return box;
  }

  function renderProfile(me) {
    const frag = document.createDocumentFragment();

    const hero = node("section", "section hero");
    hero.appendChild(node("div", "hero__name", me.display_name));
    if (me.roles.length) hero.appendChild(node("div", "hero__sub", me.roles.join(" · ")));
    const status = node("div", `status ${me.ready_for_matching ? "status--ok" : "status--wait"}`);
    status.appendChild(icon(me.ready_for_matching ? "check" : "clock", 14));
    status.appendChild(
      node("span", null, me.ready_for_matching ? "Готов к подбору" : "Профиль ещё собирается")
    );
    hero.appendChild(status);
    frag.appendChild(hero);

    if (!me.ready_for_matching && me.onboarding_question) {
      const next = node("section", "section");
      next.appendChild(node("h2", "section__title", "Следующий шаг"));
      next.appendChild(node("div", null, me.onboarding_question));
      next.appendChild(node("div", "note", "Ответь в чате с ботом — подбор включится сам."));
      frag.appendChild(next);
    }

    const facts = node("section", "section");
    facts.appendChild(node("h2", "section__title", "Профиль"));
    const rows = [
      ["Локация", me.location],
      ["Формат", me.work_mode],
      ["Языки", me.languages.join(", ")],
      ["Зарплата от", me.salary_min ? `${me.salary_min.toLocaleString("ru-RU")} ${me.salary_currency || ""}`.trim() : null],
      [
        "Приоритет",
        { job: "работа", talk: "выступления", both: "работа и выступления" }[me.priorities] ||
          me.priorities,
      ],
      ["Красные флаги", me.hard_nos],
      ["В избранном", me.saved_count ? String(me.saved_count) : null],
    ].filter(([, value]) => value);

    rows.forEach(([key, value]) => {
      const row = node("div", "row");
      row.appendChild(node("span", "row__key", key));
      row.appendChild(node("span", "row__val", value));
      facts.appendChild(row);
    });
    if (rows.length) frag.appendChild(facts);

    if (me.skills.length) {
      const skills = node("section", "section");
      skills.appendChild(node("h2", "section__title", "Навыки"));
      const chips = node("div", "chips");
      me.skills.slice(0, 24).forEach((skill) => chips.appendChild(node("span", "chip", skill)));
      skills.appendChild(chips);
      frag.appendChild(skills);
    }

    if (me.speaking_topics.length) {
      const topics = node("section", "section");
      topics.appendChild(node("h2", "section__title", "Темы выступлений"));
      const chips = node("div", "chips");
      me.speaking_topics.forEach((topic) => chips.appendChild(node("span", "chip", topic)));
      topics.appendChild(chips);
      frag.appendChild(topics);
    }

    if (me.goals) {
      const goals = node("section", "section");
      goals.appendChild(node("h2", "section__title", "Цели"));
      goals.appendChild(node("div", null, me.goals));
      frag.appendChild(goals);
    }

    frag.appendChild(buildChatActions());
    return frag;
  }

  const CHAT_ACTIONS = [
    ["file", "Обновить резюме", "Пришли новый PDF или DOCX — перезаберу профиль."],
    ["link", "Добавить ссылки", "LinkedIn, сайт, записи выступлений — просто кинь в чат."],
    ["bell", "Расписание рассылок", "Команда /schedule: дни, время и тихие часы."],
    ["trash", "Удалить профиль", "Команда /delete: сотру всё, что о тебе знаю."],
  ];

  function buildChatActions() {
    const section = node("section", "section");
    section.appendChild(node("h2", "section__title", "Это делается в чате"));

    CHAT_ACTIONS.forEach(([iconName, title, text]) => {
      const item = node("button", "listitem");
      item.type = "button";
      item.appendChild(icon(iconName, 20));

      const body = node("div", "listitem__body");
      body.appendChild(node("div", "listitem__title", title));
      body.appendChild(node("div", "listitem__text", text));
      item.appendChild(body);

      const chevron = icon("chevron", 18);
      chevron.classList.add("listitem__chevron");
      item.appendChild(chevron);

      item.addEventListener("click", () => {
        haptic("impact");
        if (tg && tg.close) tg.close();
        else toast("Открой чат с ботом");
      });
      section.appendChild(item);
    });

    section.appendChild(node("div", "note", "Нажми — закрою приложение и верну в чат."));
    return section;
  }

  function render() {
    const tab = TABS.find((t) => t.id === state.tab);
    el.title.textContent = tab.title;
    el.refresh.hidden = tab.kind !== "feed";
    el.screen.replaceChildren();

    if (state.loading[state.tab]) {
      el.screen.appendChild(skeleton(3));
      return;
    }

    const data = state.data[state.tab];
    if (data && data.error) {
      el.screen.appendChild(
        emptyState("alert", "Не получилось", data.error, {
          label: "Попробовать снова",
          onClick: () => load(state.tab, { force: true }),
        })
      );
      return;
    }

    if (tab.kind === "profile") {
      if (data) el.screen.appendChild(renderProfile(data.me));
      return;
    }

    const items = (data && data.items) || [];
    if (!items.length) {
      const notice = (data && data.notice) || EMPTY_HINTS[state.tab];
      const [iconName, title, text] = notice;
      const action =
        tab.kind === "feed" && !(data && data.notice)
          ? { label: "Поискать сейчас", onClick: () => load(state.tab, { refresh: true }) }
          : null;
      el.screen.appendChild(emptyState(iconName, title, text, action));
      return;
    }

    items.forEach((card) => el.screen.appendChild(buildCard(card, tab)));
  }

  /* ---------------- data ---------------- */

  async function load(tabId, options) {
    const opts = options || {};
    const tab = TABS.find((t) => t.id === tabId);
    if (state.loading[tabId]) return;
    if (state.data[tabId] && !opts.force && !opts.refresh) {
      render();
      return;
    }

    state.loading[tabId] = true;
    if (opts.refresh) el.refresh.classList.add("is-busy");
    render();

    try {
      if (tab.kind === "profile") {
        state.me = await api("/api/v1/me");
        state.data[tabId] = { me: state.me };
      } else if (tab.kind === "saved") {
        state.data[tabId] = { items: await api("/api/v1/saved") };
      } else if (opts.refresh) {
        const feed = await api(`/api/v1/feed/refresh?scope=${tabId}`, { method: "POST" });
        state.data[tabId] = { items: feed.items };
      } else {
        const feed = await api(`/api/v1/feed?scope=${tabId}`);
        state.data[tabId] = { items: feed.items };
      }
    } catch (error) {
      if (error.code === "no_profile") {
        showGate(
          "Профиля пока нет.\nЗагрузи резюме в чате с ботом — и возвращайся."
        );
        return;
      }
      if (error.code === "profile_not_ready") {
        state.data[tabId] = {
          items: [],
          notice: [
            "clipboard",
            "Профиль ещё не готов",
            "Допиши ответы в чате с ботом — включу подбор.",
          ],
        };
      } else {
        state.data[tabId] = { error: error.message };
      }
    } finally {
      state.loading[tabId] = false;
      el.refresh.classList.remove("is-busy");
      render();
    }
  }

  function refreshSavedBadge(delta) {
    if (state.me) state.me.saved_count = Math.max(0, (state.me.saved_count || 0) + delta);
    delete state.data.saved;
  }

  function switchTab(tabId) {
    if (state.tab === tabId) return;
    state.tab = tabId;
    haptic("selection");
    Array.from(el.tabbar.children).forEach((button) => {
      button.classList.toggle("is-active", button.dataset.tab === tabId);
    });
    render();
    load(tabId);
  }

  function buildTabbar() {
    TABS.forEach((tab) => {
      const button = node("button", `tab${tab.id === state.tab ? " is-active" : ""}`);
      button.type = "button";
      button.dataset.tab = tab.id;
      button.appendChild(icon(tab.icon));
      button.appendChild(node("span", "tab__label", tab.label));
      button.addEventListener("click", () => switchTab(tab.id));
      el.tabbar.appendChild(button);
    });
  }

  /* ---------------- boot ---------------- */

  function showGate(message) {
    el.gateText.textContent = message;
    el.gate.hidden = false;
    el.app.hidden = true;
  }

  function showApp() {
    el.gate.hidden = true;
    el.app.hidden = false;
  }

  function boot() {
    if (!tg || !tg.initData) {
      showGate("Kabi открывается только из Telegram.\nНайди бота и нажми кнопку «Открыть Kabi».");
      return;
    }

    tg.ready();
    tg.expand();
    if (tg.setHeaderColor) {
      try {
        tg.setHeaderColor("secondary_bg_color");
      } catch (_) {
        /* старые клиенты не умеют — не критично */
      }
    }
    if (tg.enableClosingConfirmation) tg.enableClosingConfirmation();

    el.refreshIcon.appendChild(icon("refresh"));
    buildTabbar();
    showApp();
    render();
    load(state.tab);

    el.refresh.addEventListener("click", () => {
      haptic("impact", "medium");
      load(state.tab, { refresh: true });
    });
    el.sheetClose.addEventListener("click", closeSheet);
    el.sheet.addEventListener("click", (event) => {
      if (event.target.dataset.close) closeSheet();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeSheet();
    });
  }

  boot();
})();
