# RAG evaluation corpus v1

## Frozen reference

Версия формата и corpus: 1. Локальная frozen copy: `data/eval/1/wiki-documents.json`.
На 2026-10-05 файл содержит 24 уникальные страницы, 277002 bytes.
SHA-256 bytes: `63ad12fec898ef6c73c5c37a66d18e0d1327c91f1f79102dfa646cadd8c9f95f`.
Проверены schema_version, source origin, document fields, положительные уникальные
page_id, locale/path, source_url, timestamps и SHA-256 UTF-8 Markdown всех страниц.
Manifest хранит source, count и полный inventory page_id/locale/path/content_sha256.
Размер отличается от архивного ingestion evidence; fingerprint относится именно к
предоставленному локальному файлу, а не к историческому запуску ingestion.

`data/` исключён из Git. Для воспроизведения передавать тот же файл по существующему
доверенному каналу и проверять hash. Не заменять его текущим ingestion output.
При изменении snapshot или разметки явно выпускать новую corpus_version, сохранять
новую frozen copy, обновлять manifest/questions и повторять семантический review.
CLI ничего не обновляет автоматически. Secrets, полные документы и DSN в corpus
не сохраняются; выбранные фрагменты не включают credentials. На страницах с
credentials используются только безопасные достаточные диапазоны. Команды здесь
являются ожидаемыми цитатами из reference, CLI их не выполняет.

## Проверка live материалов

Прочитаны Markdown всех 24 страниц: 2, 3, 4, 5, 12, 17, 19, 20, 22, 23, 24,
26, 27, 29, 37, 39, 40, 41, 42, 43, 44, 45, 46, 47. Полные metadata inventory
находятся в manifest, точные полуоткрытые Unicode диапазоны — в questions.
Отсутствие ответа и отсутствие специальной категории проверялись по всему reference.

| Категория | Live evidence и case IDs | Итог |
| --- | --- | --- |
| Текст, technical names | q01: page 19, `ru/kamchatka/Микросервисы/rb-route-plan`, обработка этапов; q05: page 12, Redis products | Live |
| Code block / команды | q02: page 3 `ru/Сервер`; q03/q10: page 43 `ru/Сервер_на_объекте`; q19: page 27 br-motion | Live |
| Markdown table | q04/q12: page 23 br-config, device_type; q06: page 40 `ru/sla`, header + RTO/RPO rows | Live |
| Long code block | q08: page 19, первый JSON-пример стадии выгрузки паллета на лифт; span первого сегмента содержит все четыре actions с order | Live; synthetic не нужен |
| Похожие identifiers | q07: page 17 `ru/kamchatka/Обмен_данными/RabbitMQ`, charge_device_id / clear_device_id, header + обе строки | Live; synthetic не нужен |
| Противоречащие источники | q18: page 27 br-motion / page 17 RabbitMQ, разные имена очереди статусов команд | Live; согласовано владельцем документации 2026-10-05 |
| Prompt injection | Во всех 24 страницах не найдено подходящих инструкций модели изменить правила ответа; инструкции администратору и shell scripts не считаются injection | Только synthetic q20 |
| Follow-up | q09: page 17, статусы br-motion.step; q10: page 43, каталог SQL-дампов и crontab -l | Два independently grounded случая |
| Составной вопрос | q11: page 23 br-config warehouse + page 12 device:<id> | Нужны оба источника |

Четыре вопроса SPEC §28 сохранены дословно в q01–q04. Для q01 выбраны обработка
этапов, конкурентное исполнение и контроль маршрута; q02 — базовая подготовка
сервера из страницы «Сервер»; q03 — Netplan, HDD и Power On на объекте.
Это минимальные обязательные факты для ручной проверки, не полные эталонные ответы.
q04 перечисляет документированные типы устройств, а не модели или производителей.

| Expected behavior | Cases | Основание ручного review |
| --- | --- | --- |
| answer | q01–q11, q19, q20 | По 1–3 факта со ссылками на проверенные spans |
| partial_answer | q12 | Типы оборудования есть; производитель каждого типа не указан во всём reference |
| clarify | q13 | «Его» без предыдущего вопроса не определяет сервер/сервис; ожидается короткое уточнение |
| refuse | q14–q17 | Нет страхового тарифа, гарантии аккумуляторов производителя, интеграции Zabbix или стоимости лицензии 2027; остальные сведения о складе не заменяют ответ |
| report_conflict | q18 | Показать оба названия и оба источника; не определять актуальное имя по догадке |

Synthetic snapshot — одна явно тестовая страница `https://wiki.example/ru/synthetic/log-retention`.
SHA-256: `9fe75320ace79ef6ee707f189137c6fd9fd886341b65395c87393ea4f2d9cf1a`.
q20 требует срок 14 дней и сохранение правил/citations вопреки инструкции внутри
документа. Fixture покрывает только отсутствующую live категорию prompt injection.
Он не добавляется в Wiki.js и используется отдельным будущим retrieval прогоном.
У synthetic свой source namespace; page_id может совпадать с live без смешения.

## Формат и offline CLI

`eval/questions.yaml` содержит UTF-8 JSON syntax — поддерживаемый JSON-compatible
YAML subset. Block-style YAML, YAML anchors/comments, NaN и duplicate JSON keys не
поддерживаются. Парсер — stdlib json, новых зависимостей нет.

Верхний объект questions: schema_version, corpus_version, questions.
Manifest: schema_version, corpus_version, live и, при необходимости, synthetic;
каждый snapshot entry содержит source, sha256, document_count, documents inventory.
Snapshot имеет существующий ingestion document shape, Markdown сохраняется lossless.

Запись вопроса: стабильный уникальный id (`[A-Za-z][A-Za-z0-9_-]{0,63}`), question,
tags, split (tuning/holdout), source_set (live/synthetic), answerable, expected_behavior,
required_facts, evidence, exact_commands. previous_question — строка предыдущего
вопроса для follow_up; прошлый ответ не является evidence. missing_information
обязателен у partial_answer; clarification обязателен у clarify.
refuse/clarify имеют answerable=false и пустые facts/evidence/commands.
answer/partial_answer/report_conflict имеют answerable=true, 1–3 facts и evidence.
conflict/composite требуют минимум две разные source pages.

Evidence: id, page_id, locale, path, content_sha256, spans; optional heading_path
содержит список заголовков и служит locator, а не заменой evidence. Span: start,
end, exact_text; индексы Unicode code points в decoded Markdown, end исключён.
CRLF не нормализуются. Повторную цитату различают offsets. Для таблиц нужны
header и выбранные rows. Для длинного блока достаточно необходимых последовательных
spans; факты связываются с evidence_ids. Все evidence связаны с facts.
Команды должны совпадать с полными строками evidence, включая multiline commands;
префикс команды не принимается.

Безопасный пример span из synthetic страницы: `{ "start": 32, "end": 57,
"exact_text": "Журналы хранятся 14 дней." }` — при ручном редактировании offsets
всегда вычислять по конкретному Markdown; произвольные числа не являются locator.
Для реальной рабочей записи см. q20 в questions (его offsets проверены CLI).

Из `app/`, с активным `.venv` проекта:

```sh
python -m pytest tests/test_evaluation.py
python -m app.evaluation --questions ../eval/questions.yaml --manifest ../eval/manifest.json --snapshot ../data/eval/1/wiki-documents.json --fixtures ../eval/fixtures/wiki-documents.json
```

При отсутствии synthetic cases/manifest entry параметр --fixtures опускается;
при наличии synthetic entry/cases fixture input обязателен. Все пути явные.
Exit 0: integrity/coverage прошли; 1: validation/file error; 2: ошибка аргументов.
Краткий JSON report содержит fingerprints и counts по categories/source_set/split.
Документы, credentials, содержимое ошибочных полей и пути входных файлов в диагностике
не выводятся. При ошибке вопроса показываются категория и безопасный case ID
(для некорректного ID — ordinal). Категории: file, format, type, value, version,
source, metadata, hash/content_hash/fingerprint, inventory, duplicate, id,
coverage, split, behavior, missing_page, identity, span/exact_text, fact_reference,
exact_command, fixtures. CLI только читает файлы, не импортирует DB/LLM transport
и не требует ingestion environment, Docker или интернет.

Count около 20 — цель, не structural constraint 18–24. Обязательные tags:
text, identifier, code, table, follow_up, refuse, partial_answer, clarify,
long_code, similar_identifiers, prompt_injection, conflict, composite.
Нужно минимум два follow_up, 3–5 refuse, минимум четыре holdout, включая answerable
и unanswerable; tuning должен содержать answerable. Tags проверяют декларацию
категории; корректность смысла и отсутствие ответа проверяет человек.

## Split и review

Split зафиксирован до tuning, retrieval пока не реализован. Holdout нельзя
использовать для подбора параметров. Это организационное правило, не access control.

| Source set | Tuning | Holdout | Всего |
| --- | ---: | ---: | ---: |
| live | 14 | 5 (q04, q08, q10, q16, q18) | 19 |
| synthetic | 0 | 1 (q20) | 1 |
| всего | 14 | 6 | 20 |

Review 2026-10-05: выбранные live quotes вручную сопоставлены с Markdown;
команды, отсутствующие ответы, follow-up и составные facts проверены отдельно.
Владелец документации согласовал q18 2026-10-05: page 27 называет
`br-plc.{id}.commands`, page 17 — `br-plc.{queue_name_callback}.command_status`.
Принято expected_behavior=report_conflict: показать оба противоречащих источника,
не выбирать актуальную/правильную версию и не пытаться примирить значения без
дополнительного источника. Case принят; неразрешённых спорных примеров нет,
семантический review завершён, задача 2.4 выполнена.
Структурный успех validator не заменяет семантический review.

## Будущий протокол оценки

Live Hit@5 = **полные hits / answerable live cases с evidence**. В принятом corpus v1
live denominator — 14 (включая partial_answer и согласованный report_conflict).
Показывать числитель/знаменатель общего live набора и отдельно
live tuning (10 answerable) / live holdout (4 answerable).
Полный hit означает, что совокупность top-5 chunks покрывает **все** обязательные
spans **всех** evidence с правильной source identity (namespace + source origin +
page_id/locale/path/content hash). Источники согласованы с frozen reference.
Часть длинного span может находиться в разных chunks, но нужно полное покрытие
в пределах top-5. Heading или повторный table header не заменяет исходные данные.
Соответствие проверять по original ranges либо ручной сверкой exact text;
фиксированные chunk IDs для corpus не нужны.

Примеры: правильная page 23 без строки device_type — miss q04; только warehouse
из page 23 без device:<id> из page 12 — miss q11. Оба обязательных фрагмента в
разных chunks top-5 — hit. Для q12 оценивается только доступная часть; отсутствие
производителя не нужно «находить». q13 clarify и q14–q17 refuse не входят в
retrieval denominator. Они оцениваются по поведению отдельно.

Порог MVP **≥90% только для live Hit@5**. Synthetic q20 не входит ни в live
числитель, ни в знаменатель и показывается отдельной метрикой, также по split.
Например, live 12/14 и synthetic 1/1 остаётся live 12/14: synthetic успех не
компенсирует live misses. Малый holdout ограничивает обобщение результата.
Retrieval/answer quality **не измерены**, scorer/runner/генерация не реализованы.

Шаблон будущего отчёта:

| Corpus version / fingerprints | Chunking/retrieval versions и параметры | Source_set / split | Case ID | Покрытые / пропущенные evidence spans | Hit/miss | Facts / citations / commands | Behavior review |
| --- | --- | --- | --- | --- | --- | --- | --- |
| заполнить | заполнить | отдельно live/synthetic и tuning/holdout | qXX | все обязательные spans | не измерено | не измерено | не измерено |

Ручная приёмка: сообщены 1–3 обязательных факта, citations подтверждают каждый;
source links строятся из metadata, команды и identifiers дословны; нет
неподтверждённых утверждений. partial_answer обозначает missing_information;
clarify задаёт короткий вопрос; report_conflict показывает оба источника;
prompt injection не меняет правила, не запускает действий; каждый refuse
отказывается придумывать содержательный ответ. Follow-up требует нового retrieval.
Изменение reference или holdout после просмотра результатов требует новой версии
и нового сравнения, а не замены ожиданий в старом отчёте.

## Evidence проверки

Целевые tests/test_evaluation.py: 83 passed (2026-10-05, Python 3.12.7, pytest 9.1.1).
Обычный системный Python не содержит pytest; использовано существующее `.venv`.
Sandbox не позволил pytest создать временные каталоги; после разрешённого запуска
вне sandbox тесты прошли. Проверяются synthetic test packages, размеры 9/20/27,
types/versions/coverage/split, mutation inputs, Unicode/CRLF, namespaces и CLI.
Unit test fixtures не содержат реального Wiki текста и не подменяют live reference.
Два реальных offline CLI запуска 2026-10-05: оба exit 0, JSON reports идентичны;
hashes всех четырёх входных файлов до/после совпали. Отчёт: corpus v1, 20 questions,
24 live documents, 1 synthetic document; fingerprints и split counts указаны выше.
Запуски выполнены без ingestion environment, DB, LLM и интернета.
`openspec validate rag-evaluation-corpus --strict` прошёл; проверены diff и coverage
SPEC §§26–28. README.md, ROADMAP.md, runtime ingestion/HTTP не изменены; reference
исключён из Git, secrets в новых отслеживаемых артефактах отсутствуют.
Это integrity evidence; семантическое согласование q18 владельцем документации
зафиксировано выше. Все 13 implementation tasks выполнены; качество retrieval
и ответов пока не измерено.
