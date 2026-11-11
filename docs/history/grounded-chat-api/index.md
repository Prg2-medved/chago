# Grounded chat API: история реализации и приёмки

Материалы перенесены сюда 2026-11-11. Текущее описание API и итогов —
[grounded-chat-api.md](../../grounded-chat-api.md). Требования —
[SPEC.md](../../../SPEC.md) и [основная спецификация](../../../openspec/specs/grounded-chat-api/spec.md);
proposal/design/tasks/delta specs остаются только в
[архиве OpenSpec](../../../openspec/changes/archive/2026-11-11-grounded-chat-api/).

Change завершён и архивирован, **36/36 задач**. Техническая приёмка принята
с исключениями владельца от 2026-11-11; stability — pass в наблюдённых
интервалах, полный corpus safety и semantic quality — fail. Отложенные
дефекты остаются post-MVP, весь MVP продукта этим change не завершён.

Статусы «открыто», «следующий шаг», «не запускалось» и прежние запреты/согласования
в документах ниже относятся к датам соответствующих записей. Даже финальная
запись журнала предшествует административному архивированию. Исторические
команды, абсолютные пути, hashes и verdicts сохранены; прежние пути документов
внутри команд и цитат могут отличаться от текущих. Markdown-ссылки обновлены.
Эти материалы не являются текущим планом или разрешением повторить серверные
действия. Исполняемые скрипты остались в `docs/` по прежним путям.

| Материал | Назначение |
|---|---|
| [Журнал приёмки](grounded-chat-api-server-acceptance.md) | Полная хронология, server evidence, failures, решения и итоговая сверка 7.4 |
| [Compose checks](grounded-chat-api-compose-checks.md) | Историческая процедура logging/concurrency/cancellation/timeout/recovery/isolation |
| [Runbook 7.2](grounded-chat-api-7.2-runbook.md) | Процедура corpus evaluation и сбора evidence |
| [App deploy](grounded-chat-api-7.2-app-deploy.md) | Установка конкретного кандидата 7.9 |
| [Runbook 7.11](grounded-chat-api-7.11-runbook.md) | Token gate и приёмка кандидата 7.9 |
| [Диагностика 7.8](grounded-chat-api-safety-diagnostic-7.8.md) | Offline диагностика и предложение механизма |
| [Кандидат 7.9](grounded-chat-api-safety-candidate-7.9.md) | Реализованное поведение и локальные регрессии 7.10 |
| [Первый review](grounded-chat-api-evaluation-review-2026-10-22.json) | Исторические case verdicts; исходная 7.2 не принята |
| [Повторный review](grounded-chat-api-evaluation-review-2026-10-22-rerun.json) | Case verdicts повторного run; прежний fail сохраняется |
| [Tuning diagnostic](grounded-chat-api-tuning-diagnostic-review-2026-10-22.json) | Выборочная диагностика, не полный acceptance run |
| [Prompt examples q01](grounded-chat-api-prompt-examples-q01-review-2026-10-22.json) | Review одного tuning case, не полная приёмка |

Отдельные [экспериментальные материалы](../../experiments/grounded-chat-api/index.md)
содержат отклонённый протокол parts и ограниченный RAM cache эксперимент.
