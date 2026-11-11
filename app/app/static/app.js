"use strict";
(() => {
  const form = document.querySelector("#question-form");
  const question = document.querySelector("#question");
  const submit = document.querySelector("#submit");
  const status = document.querySelector("#chat-status");
  const result = document.querySelector("#result");
  const health = document.querySelector("#health");
  const refresh = document.querySelector("#refresh");
  const session = globalThis.crypto?.randomUUID?.() || `page-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  let pending = false;
  let healthPending = false;
  function node(tag, text, className) {
    const element = document.createElement(tag);
    element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  function reset() {
    question.value = "";
    result.replaceChildren();
    status.textContent = "";
  }
  reset();
  window.addEventListener("pageshow", (event) => { if (event.persisted) reset(); });
  const messages = {
    422: "Некорректный вопрос или превышен допустимый объём. Сократите вопрос.",
    502: "Сервис генерации вернул некорректный ответ.",
    503: "Сервис временно недоступен. Проверьте состояние системы или обратитесь к оператору.",
    504: "Превышено время ожидания генерации. Обратитесь к оператору для проверки состояния."
  };
  function validAnswer(value) {
    return value && typeof value.answer === "string" && typeof value.insufficient_context === "boolean"
      && Array.isArray(value.sources) && value.sources.every(source => source
        && ["title", "heading", "quote", "url"].every(key => typeof source[key] === "string"));
  }
  function render(value) {
    if (value.insufficient_context) result.append(node("p", "Недостаточно сведений в документации для полного ответа.", "warning"));
    result.append(node("h2", "Ответ"), node("div", value.answer, "answer"));
    if (value.sources.length) result.append(node("h2", "Источники"));
    value.sources.forEach((source, index) => {
      const card = node("article", "", "source");
      card.append(node("h3", `${index + 1}. ${source.title}`));
      if (source.heading.trim()) card.append(node("p", source.heading));
      card.append(node("div", source.quote, "quote"));
      let url;
      try {
        url = new URL(source.url);
        if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) url = null;
      } catch { url = null; }
      if (url) {
        const link = node("a", "Открыть в Wiki.js");
        link.href = url.href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        card.append(node("p", ""));
        card.lastChild.append(link);
      } else card.append(node("p", `Ссылка недоступна: ${source.url}`));
      result.append(card);
    });
  }
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (pending) return;
    result.replaceChildren();
    status.className = "error";
    const message = question.value;
    if (!message.trim()) { status.textContent = "Введите вопрос."; return; }
    if (Array.from(message).length > 4096) { status.textContent = "Вопрос должен содержать не более 4096 символов."; return; }
    pending = true;
    submit.disabled = true;
    status.className = "";
    status.textContent = "Обрабатываем вопрос. Ожидание очереди и генерация могут занять несколько минут.";
    let errorMessage = "Ошибка связи. Проверьте подключение. Запрос автоматически не повторяется.";
    try {
      const response = await fetch("/api/chat", {method: "POST", cache: "no-store",
        headers: {"Content-Type": "application/json"}, body: JSON.stringify({session_id: session, message})});
      if (!response.ok) {
        errorMessage = messages[response.status] || "Ошибка сервера при обработке вопроса.";
        throw new Error();
      }
      errorMessage = "Сервер вернул некорректный ответ.";
      const value = await response.json();
      if (!validAnswer(value)) throw new Error();
      render(value);
      status.textContent = "";
    } catch {
      status.className = "error";
      status.textContent = errorMessage;
    } finally {
      pending = false;
      submit.disabled = false;
    }
  });
  question.addEventListener("keydown", event => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); form.requestSubmit(); }
  });
  const labels = {ok: "Работает", missing: "Индекс отсутствует", invalid: "Индекс невалиден",
    unavailable: "Недоступна", invalid_response: "Некорректный ответ", timeout: "Время ожидания истекло",
    configuration_error: "Ошибка конфигурации", available: "Генерация не заблокирована",
    generation_uncertain: "Завершение генерации не подтверждено. Требуется восстановление оператором.", closed: "Обработка закрыта"};
  function renderHealth(value) {
    if (!value || value.status !== "ok" || value.app?.status !== "ok"
        || !["ok", "missing", "invalid"].includes(value.index?.status)
        || !["ok", "unavailable", "invalid_response", "timeout", "configuration_error"].includes(value.llm?.status)
        || !["available", "generation_uncertain", "closed"].includes(value.chat?.status)
        || typeof value.index.available !== "boolean"
        || ![value.index.pages, value.index.chunks].every(count => count === null || (Number.isInteger(count) && count >= 0))
        || !(value.index.indexed_at === null || (typeof value.index.indexed_at === "string" && Number.isFinite(Date.parse(value.index.indexed_at))))) throw new Error();
    const list = document.createElement("dl");
    const date = value.index.indexed_at === null ? "Нет данных" : `${new Date(value.index.indexed_at).toISOString()} (UTC)`;
    for (const [label, text] of [["Приложение", labels[value.app.status]], ["Индекс", labels[value.index.status]],
      ["Страницы", value.index.pages ?? "Нет данных"], ["Фрагменты", value.index.chunks ?? "Нет данных"],
      ["Последняя успешная индексация", date], ["LLM", labels[value.llm.status]], ["Блокировка генерации", labels[value.chat.status]]]) {
      list.append(node("dt", label), node("dd", String(text)));
    }
    health.replaceChildren(list);
    if (value.chat.status === "generation_uncertain") health.append(node("p", labels.generation_uncertain, "warning"));
  }
  async function updateHealth() {
    if (healthPending) return;
    healthPending = true;
    refresh.disabled = true;
    health.textContent = "Проверяем состояние…";
    try {
      const response = await fetch("/health", {cache: "no-store"});
      if (!response.ok) throw new Error();
      renderHealth(await response.json());
    } catch { health.textContent = "Не удалось проверить состояние системы."; }
    finally { healthPending = false; refresh.disabled = false; }
  }
  refresh.addEventListener("click", updateHealth);
  updateHealth();
})();
