# Grounded chat API: эксперименты и отклонённые предложения

Материалы перенесены сюда 2026-11-11. Текущее состояние —
[grounded-chat-api.md](../../grounded-chat-api.md), результаты проверок —
[история приёмки](../../history/grounded-chat-api/index.md).
План и задачи не дублируются: они сохранены в
[архиве OpenSpec](../../../openspec/changes/archive/2026-11-11-grounded-chat-api/).

| Материал | Итог |
|---|---|
| [Answer parts proposal](grounded-chat-api-answer-parts-proposal.md) | Отклонён владельцем 2026-10-22, не реализован; текущий формат `{kind, answer}`. Не является выбранным post-MVP решением |
| [RAM prompt cache](grounded-chat-api-cache-ram-zero-experiment.md) | Исторический протокол ограниченной проверки `--cache-ram 0`; последующая полная серия 7.6 с утверждённым flag принята владельцем 2026-10-23 только для измеренного интервала |

Протокол RAM cache не следует путать с результатом полной серии: memory gate
закрыт по её evidence, а не по наличию инструкции. Residual +4,684 MiB
не является будущим порогом, отсутствие leak не доказано. Подробные результаты
и прежние отрицательные verdicts сохранены в
[журнале приёмки](../../history/grounded-chat-api/grounded-chat-api-server-acceptance.md).

Исторические статусы и команды относятся к своим датам. Эти документы
не задают текущие требования и не разрешают повторные runs; актуальные критерии
задаются [SPEC.md](../../../SPEC.md) и
[спецификацией API](../../../openspec/specs/grounded-chat-api/spec.md).
