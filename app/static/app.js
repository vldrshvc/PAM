/* Personal Finance Tracker: thin mobile client.
   No framework, no build step. All logic lives in the API; this file only
   renders what the API returns and posts what the user types. */

"use strict";

const TOKEN_KEY = "pam.token";
const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
const FEED_WINDOW_DAYS = 30;

const state = { view: "today", kind: "expense", categories: [], accounts: [], lastAccountId: null,
                // How far back the history feed reaches, in days. "Earlier" widens it.
                feedDays: FEED_WINDOW_DAYS };
const VIEW_TITLES = { today: "Today", month: "This month", categories: "Categories", accounts: "Accounts" };

// --- API -----------------------------------------------------------------

async function api(path, { method = "GET", body, form } = {}) {
  const headers = {};
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload;
  if (form) {
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    payload = new URLSearchParams(form);
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const response = await fetch(path, { method, headers, body: payload });
  if (response.status === 401 && path !== "/token") {
    logout();
    throw new Error("Session expired, please log in again");
  }
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(describeError(data));
  return data;
}

function describeError(data) {
  const detail = data.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg.replace(/^Value error, /, "")).join("; ");
  return "Request failed";
}

// --- helpers -------------------------------------------------------------

const $ = (selector, root = document) => root.querySelector(selector);

function money(value) {
  return `€${value}`;
}

// Local date, not UTC: an expense added at 00:30 Dublin time is today's, and
// "yesterday" in the feed must mean the user's yesterday.
function isoDate(d) {
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function todayISO() {
  return isoDate(new Date());
}

function shiftDays(iso, days) {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + days);
  return isoDate(d);
}

function categoryName(id) {
  const category = state.categories.find((c) => c.id === id);
  return category ? category.name : "?";
}

let toastTimer;
function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("error", isError);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 3000);
}

function render(templateId) {
  const view = $("#view");
  view.replaceChildren($(`#${templateId}`).content.cloneNode(true));
  return view;
}

function li({ title, sub, amount, over = false, plus = false, muted = false, onDelete, bar }) {
  const item = document.createElement("li");
  const main = document.createElement("div");
  main.className = "main";
  const t = document.createElement("div");
  t.className = "title";
  t.textContent = title;
  main.appendChild(t);
  if (sub) {
    const s = document.createElement("div");
    s.className = "sub";
    s.textContent = sub;
    main.appendChild(s);
  }
  if (bar) {
    const b = document.createElement("div");
    b.className = "bar";
    const fill = document.createElement("i");
    fill.style.width = `${Math.min(100, bar)}%`;
    if (bar > 100) fill.className = "over";
    b.appendChild(fill);
    main.appendChild(b);
  }
  item.appendChild(main);
  if (amount !== undefined) {
    const a = document.createElement("span");
    a.className = `amount${over ? " over" : ""}${plus ? " plus" : ""}${muted ? " sub" : ""}`;
    a.textContent = amount;
    item.appendChild(a);
  }
  if (onDelete) {
    const del = document.createElement("button");
    del.className = "icon";
    del.title = "Delete";
    del.textContent = "✕";
    del.addEventListener("click", onDelete);
    item.appendChild(del);
  } else if (amount !== undefined) {
    // A row that cannot be deleted still holds the column open, so amounts
    // down the list stay on one right edge.
    const spacer = document.createElement("span");
    spacer.className = "icon-gap";
    spacer.setAttribute("aria-hidden", "true");
    item.appendChild(spacer);
  }
  return item;
}

// A date rule across the feed: which day, what it cost, what came in.
function dayHeader(iso, spent, earned) {
  const item = document.createElement("li");
  item.className = "day";
  const label = document.createElement("span");
  label.className = "day-name";
  label.textContent = dayLabel(iso);
  item.appendChild(label);
  const sums = document.createElement("span");
  sums.className = "day-sums";
  if (earned > 0) {
    const plus = document.createElement("b");
    plus.className = "plus";
    plus.textContent = `+${money(earned.toFixed(2))}`;
    sums.appendChild(plus);
  }
  if (spent > 0 || earned === 0) {
    const out = document.createElement("b");
    out.textContent = money(spent.toFixed(2));
    sums.appendChild(out);
  }
  item.appendChild(sums);
  return item;
}

function dayLabel(iso) {
  const today = todayISO();
  if (iso === today) return "Today";
  if (iso === shiftDays(today, -1)) return "Yesterday";
  const d = new Date(`${iso}T00:00:00`);
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString(undefined, {
    weekday: "short", day: "numeric", month: "short",
    ...(sameYear ? {} : { year: "numeric" }),
  });
}

function fillList(listEl, items, emptyText) {
  // The view may have been replaced (tab switch, logout) while the
  // request was in flight; then there is nothing to fill.
  if (!listEl) return;
  listEl.replaceChildren(...items);
  if (items.length === 0) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = emptyText;
    listEl.appendChild(empty);
  }
}

// --- auth ----------------------------------------------------------------

function logout() {
  localStorage.removeItem(TOKEN_KEY);
  showLogin();
}

function showLogin() {
  $("#tabs").hidden = true;
  $("#screen-title").textContent = "";
  const view = render("tpl-login");
  const form = $("#login-form", view);

  async function submit(register) {
    const username = form.username.value.trim();
    const password = form.password.value;
    try {
      if (register) {
        await api("/register", { method: "POST", body: { username, password } });
        toast("Account created");
      }
      const { access_token } = await api("/token", { method: "POST", form: { username, password } });
      localStorage.setItem(TOKEN_KEY, access_token);
      await showApp();
    } catch (err) {
      toast(err.message, true);
    }
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    submit(false);
  });
  $("#register-btn", view).addEventListener("click", () => {
    if (form.reportValidity()) submit(true);
  });
}

async function showApp() {
  $("#tabs").hidden = false;
  await Promise.all([loadCategories(), loadAccounts()]);
  await showView(state.view);
}

async function loadCategories() {
  state.categories = await api("/categories");
}

async function loadAccounts() {
  state.accounts = await api("/accounts");
  if (!state.accounts.some((a) => a.id === state.lastAccountId)) state.lastAccountId = state.accounts[0]?.id ?? null;
}

function accountName(id) {
  const account = state.accounts.find((a) => a.id === id);
  return account ? account.name : "?";
}

function renderAccountOptions(select, selectedId) {
  select.replaceChildren(
    ...state.accounts.map((a) => {
      const option = document.createElement("option");
      option.value = a.id;
      option.textContent = a.subtype ? `${a.name} (${a.subtype})` : a.name;
      option.selected = a.id === selectedId;
      return option;
    })
  );
}

// --- views ---------------------------------------------------------------

async function showView(name) {
  // render() throws the sheet away with the rest of the view; the lock it put
  // on the body would outlive it.
  document.body.classList.remove("sheet-open");
  state.view = name;
  for (const button of document.querySelectorAll("#tabs button")) {
    button.classList.toggle("active", button.dataset.view === name);
  }
  $("#screen-title").textContent = VIEW_TITLES[name] ?? "";
  const views = { today: showToday, month: showMonth, categories: showCategories, accounts: showAccounts };
  try {
    await views[name]();
  } catch (err) {
    toast(err.message, true);
  }
}

async function showToday() {
  const view = render("tpl-today");
  $("#date", view).value = todayISO();
  renderCategoryOptions($("#category", view));

  $("#suggest-btn", view).addEventListener("click", suggest);
  $("#raw-text", view).addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      suggest();
    }
  });
  $("#add-form", view).addEventListener("submit", addExpense);

  $("#income-date", view).value = todayISO();
  $("#income-form", view).addEventListener("submit", addIncome);
  renderAccountOptions($("#account", view), state.lastAccountId);
  renderAccountOptions($("#income-account", view), state.lastAccountId);
  $("#transfer-date", view).value = todayISO();
  renderAccountOptions($("#transfer-from", view), state.accounts[0]?.id);
  renderAccountOptions($("#transfer-to", view), state.accounts[1]?.id ?? state.accounts[0]?.id);
  $("#transfer-form", view).addEventListener("submit", addTransfer);
  $("#target-date", view).value = todayISO();
  $("#target-form", view).addEventListener("submit", addTarget);
  for (const button of view.querySelectorAll("#kind button")) {
    button.addEventListener("click", () => setKind(button.dataset.kind));
  }
  setKind(state.kind);

  $("#load-more", view).addEventListener("click", showEarlier);
  $("#fab", view).addEventListener("click", openSheet);
  for (const el of view.querySelectorAll("[data-close]")) el.addEventListener("click", closeSheet);

  const [, count] = await Promise.all([refreshSummary(), refreshFeed()]);
  state.feedCount = count;
}

// --- the add sheet -------------------------------------------------------

// Adding is a deliberate act behind the "+", so the screen itself can stay a
// history. The sheet keeps the forms' state between openings; only the date is
// reset, because a sheet opened tomorrow should default to tomorrow.
function openSheet() {
  const sheet = $("#sheet");
  if (!sheet) return;
  for (const id of ["#date", "#income-date", "#transfer-date"]) {
    const field = $(id);
    if (field && !field.value) field.value = todayISO();
  }
  sheet.hidden = false;
  document.body.classList.add("sheet-open");
  const first = $("#sheet form:not([hidden]) input:not([type=hidden])");
  if (first) first.focus({ preventScroll: true });
}

function closeSheet() {
  const sheet = $("#sheet");
  if (!sheet || sheet.hidden) return;
  sheet.hidden = true;
  document.body.classList.remove("sheet-open");
  const fab = $("#fab");
  if (fab) fab.focus({ preventScroll: true });
}

// --- targets -------------------------------------------------------------

const STATUS_LABELS = { on_track: "On track", behind: "Behind", achieved: "Achieved", expired: "Expired" };

function renderTargets(targets) {
  const list = $("#target-list");
  if (!list) return;
  const items = targets.map((t) => {
    const by = new Date(`${t.end_date}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });
    const item = li({
      title: t.name,
      sub:
        t.status === "achieved"
          ? `${money(t.amount)} · reached`
          : t.status === "expired"
            ? `${money(t.amount)} by ${by} · missed by ${money(t.remaining)}`
            : `${money(t.remaining)} to go · ${t.days_left} day${t.days_left === 1 ? "" : "s"} left, by ${by}`,
      bar: Number(t.amount) > 0 ? Math.max(0, (Number(t.current_balance) / Number(t.amount)) * 100) : 0,
      onDelete: () => deleteTarget(t),
    });
    const main = item.querySelector(".main");
    if (t.status === "on_track" || t.status === "behind") {
      const perDay = document.createElement("div");
      perDay.className = "per-day";
      perDay.append("Need ");
      const b = document.createElement("b");
      b.textContent = `${money(t.required_per_day)}/day`;
      perDay.append(b);
      if (t.projected_date) perDay.append(` · at this pace done ${new Date(`${t.projected_date}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" })}`);
      main.appendChild(perDay);
    }
    const status = document.createElement("span");
    status.className = `status ${t.status}`;
    status.textContent = STATUS_LABELS[t.status];
    item.insertBefore(status, item.querySelector(".icon"));
    return item;
  });
  fillList(list, items, "No targets yet. Set a balance to reach by a date.");
}

async function addTarget(event) {
  event.preventDefault();
  const body = {
    name: $("#target-name").value.trim(),
    amount: $("#target-amount").value,
    end_date: $("#target-date").value,
  };
  try {
    await api(`/targets?tz=${encodeURIComponent(TZ)}`, { method: "POST", body });
    $("#target-form").reset();
    $("#target-date").value = todayISO();
    toast("Target set");
    await refreshSummary();
  } catch (err) {
    toast(err.message, true);
  }
}

async function deleteTarget(target) {
  if (!confirm(`Delete target "${target.name}"?`)) return;
  try {
    await api(`/targets/${target.id}`, { method: "DELETE" });
    await refreshSummary();
  } catch (err) {
    toast(err.message, true);
  }
}

function setKind(kind) {
  state.kind = kind;
  for (const button of document.querySelectorAll("#kind button")) {
    button.classList.toggle("active", button.dataset.kind === kind);
  }
  $("#add-form").hidden = kind !== "expense";
  $("#income-form").hidden = kind !== "income";
  $("#transfer-form").hidden = kind !== "transfer";
}

async function addTransfer(event) {
  event.preventDefault();
  const body = {
    amount: $("#transfer-amount").value,
    date: $("#transfer-date").value,
    from_account_id: Number($("#transfer-from").value),
    to_account_id: Number($("#transfer-to").value),
    description: $("#transfer-description").value.trim() || null,
  };
  try {
    await api("/transfers", { method: "POST", body });
    $("#transfer-form").reset();
    $("#transfer-date").value = todayISO();
    renderAccountOptions($("#transfer-from"), state.accounts[0]?.id);
    renderAccountOptions($("#transfer-to"), state.accounts[1]?.id ?? state.accounts[0]?.id);
    closeSheet();
    toast("Moved");
    state.feedCount = (await Promise.all([refreshSummary(), refreshFeed()]))[1];
  } catch (err) {
    toast(err.message, true);
  }
}

async function deleteTransfer(transfer) {
  if (!confirm(`Delete transfer of ${money(transfer.amount)}?`)) return;
  try {
    await api(`/transfers/${transfer.id}`, { method: "DELETE" });
    await Promise.all([refreshSummary(), refreshFeed()]);
  } catch (err) {
    toast(err.message, true);
  }
}

async function addIncome(event) {
  event.preventDefault();
  const body = {
    amount: $("#income-amount").value,
    date: $("#income-date").value,
    source: $("#income-source").value,
    account_id: Number($("#income-account").value),
    description: $("#income-description").value.trim() || null,
  };
  try {
    await api("/incomes", { method: "POST", body });
    state.lastAccountId = body.account_id;
    $("#income-form").reset();
    $("#income-date").value = todayISO();
    renderAccountOptions($("#income-account"), state.lastAccountId);
    closeSheet();
    toast("Income added");
    state.feedCount = (await Promise.all([refreshSummary(), refreshFeed()]))[1];
  } catch (err) {
    toast(err.message, true);
  }
}

async function deleteIncome(income) {
  if (!confirm(`Delete +${money(income.amount)} ${income.description || SOURCE_LABELS[income.source]}?`)) return;
  try {
    await api(`/incomes/${income.id}`, { method: "DELETE" });
    await Promise.all([refreshSummary(), refreshFeed()]);
  } catch (err) {
    toast(err.message, true);
  }
}

function renderCategoryOptions(select, selectedId) {
  select.replaceChildren(
    ...state.categories.map((c) => {
      const option = document.createElement("option");
      option.value = c.id;
      option.textContent = c.name;
      option.selected = c.id === selectedId;
      return option;
    })
  );
}

async function refreshSummary() {
  const s = await api(`/summary/daily?tz=${encodeURIComponent(TZ)}`);
  if (!$("#summary-card")) return;
  $("#balance").textContent = money(s.balance);
  $("#spent-today").textContent = money(s.spent_today);
  $("#earned-today").textContent = `+${money(s.earned_today)}`;
  $("#spent-month").textContent = money(s.spent_this_month);
  $("#account-chips").replaceChildren(
    ...s.accounts.map((a) => {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = `${a.name} `;
      const b = document.createElement("b");
      b.textContent = money(a.balance);
      chip.appendChild(b);
      return chip;
    })
  );
  const remaining = $("#remaining");
  remaining.textContent = s.budget_total === "0.00" ? "no budget" : money(s.remaining_total);
  remaining.classList.toggle("over", s.over_budget);
  renderTargets(s.targets);
}

const SOURCE_LABELS = { work: "Work", friend: "Friend", debt: "Debt", bonus: "Bonus", other: "Other" };

// The main screen is a history: every entry, newest first, cut into days.
// The window starts at 30 days and "Earlier" widens it, so the first paint
// stays small on a phone but nothing is out of reach.
async function refreshFeed() {
  const to = todayISO();
  const range = `date_from=${shiftDays(to, -(state.feedDays - 1))}&date_to=${to}`;
  const [expenses, incomes, transfers] = await Promise.all([
    api(`/expenses?${range}`),
    api(`/incomes?${range}`),
    api(`/transfers?${range}`),
  ]);

  // One bucket per day, each already newest-first inside its own kind.
  const days = new Map();
  const bucket = (date) => {
    if (!days.has(date)) days.set(date, { spent: 0, earned: 0, rows: [] });
    return days.get(date);
  };
  for (const e of expenses) {
    const day = bucket(e.date);
    day.spent += Number(e.price);
    day.rows.push(
      li({
        title: e.description || categoryName(e.category_id),
        sub: [e.description ? categoryName(e.category_id) : "", accountName(e.account_id)].filter(Boolean).join(" · "),
        amount: money(e.price),
        onDelete: () => deleteExpense(e),
      })
    );
  }
  for (const i of incomes) {
    const day = bucket(i.date);
    day.earned += Number(i.amount);
    day.rows.push(
      li({
        title: i.description || SOURCE_LABELS[i.source],
        sub: [i.description ? SOURCE_LABELS[i.source] : "", accountName(i.account_id)].filter(Boolean).join(" · "),
        amount: `+${money(i.amount)}`,
        plus: true,
        onDelete: () => deleteIncome(i),
      })
    );
  }
  // Transfers move money without spending or earning it, so they are listed
  // but never counted into a day's totals.
  for (const t of transfers) {
    bucket(t.date).rows.push(
      li({
        title: `${accountName(t.from_account_id)} → ${accountName(t.to_account_id)}`,
        sub: t.description || "transfer",
        amount: money(t.amount),
        muted: true,
        onDelete: () => deleteTransfer(t),
      })
    );
  }

  const items = [];
  for (const date of [...days.keys()].sort().reverse()) {
    const day = days.get(date);
    items.push(dayHeader(date, day.spent, day.earned), ...day.rows);
  }
  fillList($("#feed"), items, `Nothing in the last ${state.feedDays} days.`);
  return expenses.length + incomes.length + transfers.length;
}

// Widening the window is the only way to learn whether anything is back there,
// so the button reports what it found instead of guessing beforehand.
async function showEarlier() {
  const button = $("#load-more");
  const before = state.feedCount ?? 0;
  state.feedDays += FEED_WINDOW_DAYS;
  button.disabled = true;
  try {
    state.feedCount = await refreshFeed();
    if (state.feedCount === before) {
      button.textContent = "Nothing earlier";
    } else {
      button.disabled = false;
    }
  } catch (err) {
    state.feedDays -= FEED_WINDOW_DAYS;
    button.disabled = false;
    toast(err.message, true);
  }
}

async function suggest() {
  const text = $("#raw-text").value.trim();
  const note = $("#suggest-note");
  if (!text) return;
  const button = $("#suggest-btn");
  button.disabled = true;
  button.textContent = "Thinking…";
  note.textContent = "Asking the model, free-tier providers can take a few seconds.";
  note.classList.remove("warn");
  note.hidden = false;
  try {
    const result = await api("/categorize", { method: "POST", body: { text } });
    if (result.amount) $("#price").value = result.amount;
    renderCategoryOptions($("#category"), result.category.id);
    $("#description").value = text.replace(/[€$£]?\s*\d+([.,]\d{1,2})?\s*(eur|euro|euros)?/i, "").trim();
    note.textContent = result.fell_back
      ? "Couldn't match a category, pick one yourself."
      : `Suggested: ${result.category.name}`;
    note.classList.toggle("warn", result.fell_back);
    note.hidden = false;
  } catch (err) {
    note.textContent = `${err.message}. Pick a category yourself or try again.`;
    note.classList.add("warn");
    toast(err.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "Suggest";
  }
}

async function addExpense(event) {
  event.preventDefault();
  const body = {
    price: $("#price").value,
    date: $("#date").value,
    category_id: Number($("#category").value),
    account_id: Number($("#account").value),
    description: $("#description").value.trim() || null,
  };
  try {
    await api("/expenses", { method: "POST", body });
    state.lastAccountId = body.account_id;
    $("#add-form").reset();
    $("#date").value = todayISO();
    $("#suggest-note").hidden = true;
    renderCategoryOptions($("#category"));
    renderAccountOptions($("#account"), state.lastAccountId);
    closeSheet();
    toast("Added");
    state.feedCount = (await Promise.all([refreshSummary(), refreshFeed()]))[1];
  } catch (err) {
    toast(err.message, true);
  }
}

async function deleteExpense(expense) {
  if (!confirm(`Delete ${money(expense.price)} ${expense.description || ""}?`)) return;
  try {
    await api(`/expenses/${expense.id}`, { method: "DELETE" });
    await Promise.all([refreshSummary(), refreshFeed()]);
  } catch (err) {
    toast(err.message, true);
  }
}

async function showMonth() {
  render("tpl-month");
  const s = await api(`/summary/monthly?tz=${encodeURIComponent(TZ)}`);
  $("#month-title").textContent = new Date(`${s.month}-01T00:00:00`).toLocaleDateString(undefined, { month: "long", year: "numeric" });
  $("#m-spent").textContent = money(s.spent_total);
  $("#m-earned").textContent = `+${money(s.earned_total)}`;
  const net = Number(s.earned_total) - Number(s.spent_total);
  $("#m-net").textContent = `${net < 0 ? "-" : "+"}${money(Math.abs(net).toFixed(2))}`;
  $("#m-net").classList.toggle("over", net < 0);
  const remaining = $("#m-remaining");
  remaining.textContent = s.budget_total === "0.00" ? "no budget" : money(s.remaining_total);
  remaining.classList.toggle("over", s.over_budget);

  const rows = s.categories
    .filter((c) => c.monthly_limit !== null || c.spent !== "0.00")
    .map((c) =>
      li({
        title: c.name,
        sub: c.monthly_limit === null ? "no limit" : `${money(c.spent)} of ${money(c.monthly_limit)}`,
        amount: c.monthly_limit === null ? money(c.spent) : `${c.remaining < 0 ? "-" : ""}${money(Math.abs(c.remaining).toFixed(2))} left`,
        over: c.over_budget,
        bar: c.monthly_limit === null ? undefined : (Number(c.spent) / Number(c.monthly_limit)) * 100,
      })
    );
  fillList($("#month-list"), rows, "No spending this month.");
}

async function showCategories() {
  const view = render("tpl-categories");
  $("#cat-form", view).addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = { name: $("#cat-name").value.trim() };
    const limit = $("#cat-limit").value;
    if (limit) body.monthly_limit = limit;
    try {
      await api("/categories", { method: "POST", body });
      await loadCategories();
      await showCategories();
      toast("Category added");
    } catch (err) {
      toast(err.message, true);
    }
  });
  renderCategoryList();
}

// --- accounts ------------------------------------------------------------

const TYPE_LABELS = { debit: "Debit card", cash: "Cash", other: "Other" };

async function showAccounts() {
  const view = render("tpl-accounts");
  $("#acc-form", view).addEventListener("submit", saveAccount);
  $("#acc-cancel", view).addEventListener("click", () => resetAccountForm());
  $("#logout", view).addEventListener("click", logout);
  await loadAccounts();
  renderAccountList();
}

function resetAccountForm() {
  const form = $("#acc-form");
  form.reset();
  $("#acc-id").value = "";
  $("#acc-submit").textContent = "Add account";
  $("#acc-cancel").hidden = true;
}

function editAccount(account) {
  $("#acc-id").value = account.id;
  $("#acc-name").value = account.name;
  $("#acc-type").value = account.type;
  $("#acc-subtype").value = account.subtype || "";
  $("#acc-opening").value = account.opening_balance;
  $("#acc-submit").textContent = "Save";
  $("#acc-cancel").hidden = false;
  $("#acc-name").focus();
}

async function saveAccount(event) {
  event.preventDefault();
  const id = $("#acc-id").value;
  const body = {
    name: $("#acc-name").value.trim(),
    type: $("#acc-type").value,
    subtype: $("#acc-subtype").value.trim() || null,
    opening_balance: $("#acc-opening").value || "0",
  };
  try {
    if (id) {
      await api(`/accounts/${id}`, { method: "PATCH", body });
      toast("Account saved");
    } else {
      await api("/accounts", { method: "POST", body });
      toast("Account added");
    }
    resetAccountForm();
    await loadAccounts();
    renderAccountList();
  } catch (err) {
    toast(err.message, true);
  }
}

function renderAccountList() {
  const items = state.accounts.map((a) =>
    li({
      title: a.name,
      // The bank only earns a mention when it is not already the account's name;
      // the opening balance lives in the edit form, where it can be changed.
      sub: a.subtype && a.subtype !== a.name ? `${TYPE_LABELS[a.type]} · ${a.subtype}` : TYPE_LABELS[a.type],
      amount: money(a.balance),
      over: Number(a.balance) < 0,
      onDelete: a.is_default ? undefined : () => deleteAccount(a),
    })
  );
  items.forEach((item, i) => item.querySelector(".main").addEventListener("click", () => editAccount(state.accounts[i])));
  fillList($("#acc-list"), items, "No accounts.");
}

async function deleteAccount(account) {
  if (!confirm(`Delete "${account.name}"? Its history and opening balance move to your default account.`)) return;
  try {
    await api(`/accounts/${account.id}`, { method: "DELETE" });
    await loadAccounts();
    renderAccountList();
  } catch (err) {
    toast(err.message, true);
  }
}

function renderCategoryList() {
  const items = state.categories.map((c) => {
    const protectedName = c.name === "uncategorized";
    return li({
      title: c.name,
      sub: c.monthly_limit === null ? "no limit · tap to set" : `limit ${money(c.monthly_limit)} · tap to change`,
      onDelete: protectedName ? undefined : () => deleteCategory(c),
    });
  });
  items.forEach((item, i) => item.querySelector(".main").addEventListener("click", () => editLimit(state.categories[i])));
  fillList($("#cat-list"), items, "No categories.");
}

async function editLimit(category) {
  const input = prompt(`Monthly limit for ${category.name} (blank to remove):`, category.monthly_limit ?? "");
  if (input === null) return;
  const monthly_limit = input.trim() === "" ? null : input.trim();
  try {
    await api(`/categories/${category.id}`, { method: "PATCH", body: { monthly_limit } });
    await loadCategories();
    renderCategoryList();
  } catch (err) {
    toast(err.message, true);
  }
}

async function deleteCategory(category) {
  if (!confirm(`Delete "${category.name}"? Its expenses move to uncategorized.`)) return;
  try {
    await api(`/categories/${category.id}`, { method: "DELETE" });
    await loadCategories();
    renderCategoryList();
  } catch (err) {
    toast(err.message, true);
  }
}

// --- boot ----------------------------------------------------------------

document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeSheet();
});

if (localStorage.getItem(TOKEN_KEY)) {
  showApp().catch(() => showLogin());
} else {
  showLogin();
}
