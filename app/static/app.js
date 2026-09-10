/* Personal Finance Tracker: thin mobile client.
   No framework, no build step. All logic lives in the API; this file only
   renders what the API returns and posts what the user types. */

"use strict";

const TOKEN_KEY = "pam.token";
const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

const state = { view: "today", kind: "expense", categories: [], accounts: [], lastAccountId: null };

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

function todayISO() {
  // Local date, not UTC: an expense added at 00:30 Dublin time is today's.
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
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
  }
  return item;
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
  state.view = name;
  for (const button of document.querySelectorAll("#tabs button")) {
    button.classList.toggle("active", button.dataset.view === name);
  }
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
  for (const button of view.querySelectorAll("#kind button")) {
    button.addEventListener("click", () => setKind(button.dataset.kind));
  }
  setKind(state.kind);

  await Promise.all([refreshSummary(), refreshTodayList()]);
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
    toast("Moved");
    await Promise.all([refreshSummary(), refreshTodayList()]);
  } catch (err) {
    toast(err.message, true);
  }
}

async function deleteTransfer(transfer) {
  if (!confirm(`Delete transfer of ${money(transfer.amount)}?`)) return;
  try {
    await api(`/transfers/${transfer.id}`, { method: "DELETE" });
    await Promise.all([refreshSummary(), refreshTodayList()]);
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
    toast("Income added");
    await Promise.all([refreshSummary(), refreshTodayList()]);
  } catch (err) {
    toast(err.message, true);
  }
}

async function deleteIncome(income) {
  if (!confirm(`Delete +${money(income.amount)} ${income.description || SOURCE_LABELS[income.source]}?`)) return;
  try {
    await api(`/incomes/${income.id}`, { method: "DELETE" });
    await Promise.all([refreshSummary(), refreshTodayList()]);
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
}

const SOURCE_LABELS = { work: "Work", friend: "Friend", debt: "Debt", bonus: "Bonus", other: "Other" };

async function refreshTodayList() {
  const today = todayISO();
  const [expenses, incomes, transfers] = await Promise.all([
    api(`/expenses?date_from=${today}&date_to=${today}`),
    api(`/incomes?date_from=${today}&date_to=${today}`),
    api(`/transfers?date_from=${today}&date_to=${today}`),
  ]);
  const items = [
    ...transfers.map((t) =>
      li({
        title: `${accountName(t.from_account_id)} → ${accountName(t.to_account_id)}`,
        sub: t.description || "transfer",
        amount: money(t.amount),
        muted: true,
        onDelete: () => deleteTransfer(t),
      })
    ),
    ...incomes.map((i) =>
      li({
        title: i.description || SOURCE_LABELS[i.source],
        sub: [i.description ? SOURCE_LABELS[i.source] : "", accountName(i.account_id)].filter(Boolean).join(" · "),
        amount: `+${money(i.amount)}`,
        plus: true,
        onDelete: () => deleteIncome(i),
      })
    ),
    ...expenses.map((e) =>
      li({
        title: e.description || categoryName(e.category_id),
        sub: [e.description ? categoryName(e.category_id) : "", accountName(e.account_id)].filter(Boolean).join(" · "),
        amount: money(e.price),
        onDelete: () => deleteExpense(e),
      })
    ),
  ];
  fillList($("#today-list"), items, "Nothing yet today.");
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
    toast("Added");
    await Promise.all([refreshSummary(), refreshTodayList()]);
  } catch (err) {
    toast(err.message, true);
  }
}

async function deleteExpense(expense) {
  if (!confirm(`Delete ${money(expense.price)} ${expense.description || ""}?`)) return;
  try {
    await api(`/expenses/${expense.id}`, { method: "DELETE" });
    await Promise.all([refreshSummary(), refreshTodayList()]);
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
      title: a.subtype ? `${a.name} · ${a.subtype}` : a.name,
      sub: `${TYPE_LABELS[a.type]} · opening ${money(a.opening_balance)}`,
      amount: money(a.balance),
      over: Number(a.balance) < 0,
      onDelete: a.name === "General" ? undefined : () => deleteAccount(a),
    })
  );
  items.forEach((item, i) => item.querySelector(".main").addEventListener("click", () => editAccount(state.accounts[i])));
  fillList($("#acc-list"), items, "No accounts.");
}

async function deleteAccount(account) {
  if (!confirm(`Delete "${account.name}"? Its history and opening balance move to General.`)) return;
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

if (localStorage.getItem(TOKEN_KEY)) {
  showApp().catch(() => showLogin());
} else {
  showLogin();
}
