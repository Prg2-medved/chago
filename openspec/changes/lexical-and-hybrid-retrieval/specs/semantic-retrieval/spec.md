# Spec Delta

## MODIFIED Requirements

### Requirement: Ranked semantic chunk search
Система SHALL возвращать top-k chunks по cosine similarity нормализованных embeddings, с default k=10 и явно заданным положительным целым k. При k больше inventory SHALL возвращаться все chunks, при пустом inventory — пустой список. Результаты SHALL сортироваться по убыванию score и при равенстве по chunk ID по возрастанию. Каждый результат SHALL содержать rank, finite score, chunk ID и исходные metadata/provenance для lookup и дословного цитирования; source namespaces SHALL NOT смешиваться. Scores SHALL NOT считаться вероятностью ответа либо основанием автоматического отказа. Pure semantic API/CLI SHALL NOT выполнять lexical search, RRF, reranking или генерацию ответов; отдельный hybrid mode SHALL быть вправе использовать этот semantic ranking как одну из веток, сохраняя прежний контракт pure semantic поиска.

#### Scenario: Known nearest vectors and ties
- **WHEN** query сравнивается с заранее известными нормализованными vectors, включая одинаковые scores
- **THEN** top-k и scores соответствуют cosine similarity, порядок ties стабилен, rank начинается с 1

#### Scenario: Source evidence preserved
- **WHEN** найден chunk с code/table continuation
- **THEN** результат сохраняет source identity, URL, headings, ranges и continuation metadata; generated segments не представлены дословной цитатой

#### Scenario: Ordinary retrieval uses only the supplied question
- **WHEN** вызывается `search(question, k)` или query CLI
- **THEN** retrieval SHALL использовать только переданный вопрос без хранения истории, context resolution или query rewriting

#### Scenario: Semantic branch reused by hybrid mode
- **WHEN** отдельный hybrid mode получает semantic candidates совместимого snapshot
- **THEN** кандидаты имеют прежние cosine scores/order/provenance, а fusion выполняется отдельным режимом без изменения pure semantic API/CLI
