// Browser acceptance harness: native CDP, no npm packages or runtime dependencies.
import {spawn} from "node:child_process";
import assert from "node:assert/strict";
import {setTimeout as delay} from "node:timers/promises";

const [browserPath, base, profile] = process.argv.slice(2);
const browser = spawn(browserPath, ["--headless=new", "--disable-gpu", "--no-first-run",
  "--no-default-browser-check", "--disable-background-networking", "--no-proxy-server", "--remote-debugging-port=0",
  `--user-data-dir=${profile}`, "about:blank"], {windowsHide: true});
let socket;
try {
  const endpoint = await new Promise((resolve, reject) => {
    let output = "";
    const timer = setTimeout(() => reject(new Error("Browser startup timeout")), 15000);
    browser.stderr.on("data", data => {
      output += data;
      const match = output.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) { clearTimeout(timer); resolve(match[1]); }
    });
    browser.on("error", reject);
    browser.on("exit", code => { clearTimeout(timer); reject(new Error(`Browser exited: ${code}`)); });
  });
  const debugOrigin = endpoint.replace(/^ws:/, "http:").split("/devtools/")[0];
  const version = await (await fetch(`${debugOrigin}/json/version`)).json();
  const target = await (await fetch(`${debugOrigin}/json/new?about:blank`, {method: "PUT"})).json();
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let id = 0;
  const waiting = new Map();
  const listeners = new Map();
  socket.onmessage = event => {
    const value = JSON.parse(event.data);
    if (value.id) {
      const callback = waiting.get(value.id);
      waiting.delete(value.id);
      if (value.error) callback.reject(new Error(JSON.stringify(value.error))); else callback.resolve(value.result);
    } else for (const listener of listeners.get(value.method) || []) listener(value.params);
  };
  function send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const call = ++id;
      waiting.set(call, {resolve, reject});
      socket.send(JSON.stringify({id: call, method, params}));
    });
  }
  function on(event, listener) { listeners.set(event, [...(listeners.get(event) || []), listener]); }
  async function evaluate(expression) {
    const response = await send("Runtime.evaluate", {expression, returnByValue: true, awaitPromise: true});
    if (response.exceptionDetails) throw new Error(JSON.stringify(response.exceptionDetails));
    return response.result.value;
  }
  async function until(expression) {
    for (let i = 0; i < 250; i++) { if (await evaluate(expression)) return; await delay(20); }
    throw new Error(`Timed out: ${expression}`);
  }
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Fetch.enable", {patterns: [{urlPattern: "*"}]});
  let chatReply = {answer: "Ответ [1] [2]\n  команда", insufficient_context: false, sources: [
    {title: "<img src=x onerror=alert(1)>", heading: "<script>alert(1)</script>", quote: "  команда\n    --flag\n<script>alert(1)</script>" + "длинныйфрагмент".repeat(200), url: "https://wiki.example/page"},
    {title: "Второй", heading: "", quote: "точный fragment", url: "javascript:alert(1)"}]};
  const goodHealth = {status: "ok", app: {status: "ok"}, index: {status: "ok", available: true,
    pages: 20, chunks: 123, indexed_at: "2026-11-11T08:00:00Z"}, llm: {status: "ok"}, chat: {status: "available"}};
  let healthReply = goodHealth;
  let chatCode = 200;
  let chatRaw = false;
  let healthCode = 200;
  let networkFailure = false;
  let hold = false;
  const held = [];
  const posts = [];
  const requests = [];
  const external = [];
  const externalResponses = [];
  const offlineCanary = "https://offline-probe.invalid/browser-matrix-canary";
  let blockedCanaries = 0;
  const browserErrors = [];
  on("Runtime.exceptionThrown", event => browserErrors.push(event));
  on("Network.responseReceived", event => {
    if (!event.response.url.startsWith(base + "/")) externalResponses.push(new URL(event.response.url).origin);
  });
  async function fulfill(requestId, code, body, raw = false) {
    return send("Fetch.fulfillRequest", {requestId, responseCode: code,
      responseHeaders: [{name: "Content-Type", value: "application/json"}],
      body: Buffer.from(raw ? body : JSON.stringify(body)).toString("base64")});
  }
  on("Fetch.requestPaused", async event => {
    try {
      const {requestId, request} = event;
      requests.push(request.url);
      if (request.url === offlineCanary) {
        blockedCanaries += 1;
        await send("Fetch.failRequest", {requestId, errorReason: "InternetDisconnected"});
      } else if (!request.url.startsWith(base + "/")) {
        external.push(request.url);
        await send("Fetch.failRequest", {requestId, errorReason: "InternetDisconnected"});
      } else if (request.url.endsWith("/api/chat")) {
        posts.push(JSON.parse(request.postData));
        if (hold) held.push(requestId);
        else if (networkFailure) await send("Fetch.failRequest", {requestId, errorReason: "InternetDisconnected"});
        else await fulfill(requestId, chatCode, chatReply, chatRaw);
      } else if (request.url.endsWith("/health")) await fulfill(requestId, healthCode, healthReply);
      else await send("Fetch.continueRequest", {requestId});
    } catch (error) { browserErrors.push(String(error)); }
  });
  // Probe the deny rule before navigating to the app's CSP-protected document.
  // Fetch interception rejects this test-only request before network transport;
  // the same rule stays active for the entire matrix while LAN remains allowed.
  const canaryRejected = await evaluate(`fetch(${JSON.stringify(offlineCanary)}, {mode:'no-cors'}).then(() => false, () => true)`);
  assert.ok(canaryRejected);
  assert.equal(blockedCanaries, 1);
  await send("Page.navigate", {url: base + "/"});
  await until('document.querySelector("#health dl") && !document.querySelector("#refresh").disabled');
  const verdicts = [];
  function pass(name) {
    verdicts.push({check: name, verdict: "PASS"});
    console.error(`PASS: ${name}`);
  }
  async function ask(message) {
    await evaluate(`document.querySelector('#question').value=${JSON.stringify(message)};document.querySelector('#question-form').requestSubmit()`);
  }
  async function settled() { await until('!document.querySelector("#submit").disabled'); }
  assert.match(await evaluate('document.querySelector("#health").textContent'), /UTC/);
  assert.match(await evaluate('document.querySelector("#health").textContent'), /123/);
  pass("health counts and UTC date");
  // Validate locally without the browser's built-in required-field interception.
  await evaluate("document.querySelector('#question-form').noValidate=true");
  const before = posts.length;
  await ask("   ");
  assert.match(await evaluate('document.querySelector("#chat-status").textContent'), /Введите/);
  await ask("🧪".repeat(4097));
  assert.match(await evaluate('document.querySelector("#chat-status").textContent'), /4096/);
  assert.equal(posts.length, before);
  pass("blank and 4097 Unicode code points rejected locally");
  hold = true;
  await ask("Первый вопрос");
  await until("document.querySelector('#submit').disabled");
  for (let i = 0; i < 100 && !held.length; i++) await delay(20);
  assert.equal(held.length, 1);
  await evaluate("document.querySelector('#question-form').dispatchEvent(new Event('submit',{cancelable:true}));document.querySelector('#submit').click()");
  await send("Input.dispatchKeyEvent", {type: "keyDown", key: "Enter", code: "Enter", modifiers: 2});
  await send("Input.dispatchKeyEvent", {type: "keyUp", key: "Enter", code: "Enter", modifiers: 2});
  await delay(100);
  assert.equal(held.length, 1);
  assert.deepEqual(Object.keys(posts[0]).sort(), ["message", "session_id"]);
  assert.ok(posts[0].session_id && posts[0].session_id.length <= 128);
  await fulfill(held.shift(), 200, chatReply);
  hold = false;
  await settled();
  pass("one POST while pending, exact payload and memory session");
  assert.equal(await evaluate('document.querySelectorAll("#result .source").length'), 2);
  assert.equal(await evaluate('document.querySelectorAll("#result img, #result script").length'), 0);
  assert.equal(await evaluate('document.querySelectorAll("#result a").length'), 1);
  assert.equal(await evaluate('document.querySelector("#result a").rel'), "noopener noreferrer");
  assert.equal(await evaluate('document.querySelector(".quote").textContent'), chatReply.sources[0].quote);
  assert.equal(await evaluate('getComputedStyle(document.querySelector(".quote")).whiteSpace'), "pre-wrap");
  assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'));
  assert.equal(await evaluate('document.querySelector(".answer").textContent'), chatReply.answer);
  pass("literal HTML, multiple citations, multiline whitespace, long fragment wrapping and safe link");
  await send("Emulation.setDeviceMetricsOverride", {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
  assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'));
  await send("Emulation.clearDeviceMetricsOverride");
  pass("390px viewport long fragment remains readable");
  healthCode = 503;
  await evaluate("document.querySelector('#refresh').click()");
  await until('!document.querySelector("#refresh").disabled');
  assert.match(await evaluate('document.querySelector("#health").textContent'), /Не удалось/);
  assert.equal(await evaluate('document.querySelector(".answer").textContent'), chatReply.answer);
  pass("health failure preserves answer without chat retry");
  hold = true;
  await ask("Следующий вопрос");
  assert.equal(await evaluate('document.querySelector("#result").textContent'), "");
  for (let i = 0; i < 100 && !held.length; i++) await delay(20);
  chatReply = {answer: "Недостаточно сведений", insufficient_context: true, sources: []};
  await fulfill(held.shift(), 200, chatReply);
  hold = false;
  await settled();
  assert.match(await evaluate('document.querySelector("#result").textContent'), /Недостаточно/);
  assert.equal(await evaluate('document.querySelectorAll(".source").length'), 0);
  assert.equal(posts[0].session_id, posts[1].session_id);
  assert.equal(posts[1].message, "Следующий вопрос");
  pass("next question replaces result; insufficient context with empty sources");
  chatReply.sources = ["javascript:alert(1)", "data:text/html,x", "https://user:pass@wiki.example/page"].map(url => ({title: "Источник", heading: "", quote: "Текст", url}));
  await ask("Частичный ответ");
  await settled();
  assert.equal(await evaluate('document.querySelectorAll("#result a").length'), 0);
  assert.equal(await evaluate('document.querySelectorAll(".source").length'), 3);
  pass("insufficient context with sources; javascript/data/credential URLs not clickable");
  for (const code of [422, 502, 503, 504, 500]) {
    chatCode = code;
    chatReply = {detail: "SECRET upstream exception"};
    const count = posts.length;
    await ask("Ошибка");
    await settled();
    const text = await evaluate('document.querySelector("#chat-status").textContent');
    assert.ok(text && !text.includes("SECRET"));
    await delay(50);
    assert.equal(posts.length, count + 1);
  }
  pass("422/502/503/504/500 safe errors, pending released, no retry");
  chatCode = 200;
  for (const value of [null, {answer: "wrong"}, "{broken"]) {
    chatRaw = typeof value === "string";
    chatReply = value;
    await ask("Некорректный ответ");
    await settled();
    assert.match(await evaluate('document.querySelector("#chat-status").textContent'), /некорректный ответ/);
  }
  chatRaw = false;
  networkFailure = true;
  await ask("Сеть");
  await settled();
  assert.match(await evaluate('document.querySelector("#chat-status").textContent'), /Ошибка связи/);
  networkFailure = false;
  pass("malformed JSON/envelope and network error finish pending");
  healthCode = 200;
  healthReply = {...goodHealth, index: {status: "missing", available: false, pages: null, chunks: null, indexed_at: null}, chat: {status: "generation_uncertain"}};
  await evaluate("document.querySelector('#refresh').click()");
  await until('!document.querySelector("#refresh").disabled');
  assert.match(await evaluate('document.querySelector("#health").textContent'), /Нет данных/);
  assert.match(await evaluate('document.querySelector("#health .warning").textContent'), /оператором/);
  pass("null metadata and generation uncertainty warning independent of llm ok");
  await send("Page.reload", {ignoreCache: true});
  await until('document.querySelector("#health dl") && !document.querySelector("#refresh").disabled');
  assert.equal(await evaluate('document.querySelector("#question").value'), "");
  assert.equal(await evaluate('document.querySelector("#result").textContent'), "");
  assert.equal(await evaluate('localStorage.length + sessionStorage.length'), 0);
  assert.equal(await evaluate('document.cookie'), "");
  pass("reload blank; no localStorage/sessionStorage/cookies");
  // Real keyboard submit through the registered Ctrl+Enter handler.
  chatReply = {answer: "Проверка клавиатуры", insufficient_context: false, sources: []};
  const count = posts.length;
  await evaluate("document.querySelector('#question').value='Клавиатура';document.querySelector('#question').focus()");
  await send("Input.dispatchKeyEvent", {type: "keyDown", key: "Enter", code: "Enter", modifiers: 2});
  await send("Input.dispatchKeyEvent", {type: "keyUp", key: "Enter", code: "Enter", modifiers: 2});
  await until('document.querySelector(".answer")?.textContent === "Проверка клавиатуры"');
  assert.equal(posts.length, count + 1);
  pass("keyboard Ctrl+Enter submit");
  // This Windows host's antivirus injects this script outside application code,
  // even with CSP. Keep the attempts visible in evidence and block them; all
  // other external page requests are a failure.
  const environmentRequests = external.filter(url => new URL(url).hostname === "gc.kis.v2.scr.kaspersky-labs.com");
  const applicationExternalRequests = external.filter(url => !environmentRequests.includes(url));
  assert.deepEqual(applicationExternalRequests, []);
  assert.deepEqual(externalResponses, []);
  assert.deepEqual(browserErrors, []);
  pass("application resources same-origin; external requests blocked (environment injection reported separately)");
  pass("offline internet-denial canary rejected before transport; full matrix works with LAN allowed");
  console.log(JSON.stringify({browser: version.Browser, base, secureContext: await evaluate("isSecureContext"),
    randomUUID: await evaluate("typeof crypto.randomUUID"), verdicts, posts: posts.length,
    environmentRequests: environmentRequests.map(url => ({origin: new URL(url).origin, action: "blocked-before-transport"})),
    applicationExternalRequests, externalResponses,
    applicationResourcePaths: [...new Set(requests.filter(url => url.startsWith(base + "/")).map(url => new URL(url).pathname))],
    offline: {mode: "browser-target external requests denied; LAN allowed", blockedCanaries, canaryRejected},
    browserErrors}, null, 2));
} finally {
  if (socket) socket.close();
  browser.kill();
}
