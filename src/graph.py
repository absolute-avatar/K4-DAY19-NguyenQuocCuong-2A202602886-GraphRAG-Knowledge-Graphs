"""Knowledge Graph (Neo4j) + GraphRAG over two drug-topic knowledge bases.

Contract (fixed — bench_kg.py and the tests rely on it):
    link_entity(name, known)                       -> one of `known` or None          (TODO KG-1)
    build_graph(graph, law_docs, news_docs, llm_fn)   load both KBs into Neo4j      (TODO KG-2)
        every node created from ONE document carries the property `doc_id`
    Neo4jGraph.context(question, doc_ids)         -> list[str] facts               (TODO KG-3)
    GraphRAGAgent.answer(question, top_k)         -> str                           (TODO KG-4)

Everything else in this file is a HINT: one possible ontology (below). Use it as is, change it,
or design your own — your own ontology + report/ONTOLOGY.md earns the bonus (see SUBMISSION.md).

Suggested ontology (Crime is the bridge between the law KB and the news KB):

    (:Article {id, title, law, doc_id})-[:DEFINES]->(:Crime {name})
    (:Article)-[:HAS_CLAUSE]->(:Clause {id, number, penalty, text})-[:MENTIONS]->(:Substance {name})
    (:Case {name, summary, date, doc_id})-[:CHARGED_WITH]->(:Crime)
    (:Case)-[:INVOLVES {amount}]->(:Substance)
    (:Case)-[:LOCATED_IN]->(:Location {name})
    (:Person {name, aliases})-[:INVOLVED_IN {role, sentence, charge}]->(:Case)
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Any, Callable

from .models import Document
from .store import EmbeddingStore

# Canonical substance names: the ones BLHS Chương XX lists, plus common ones in Vietnamese news.
SUBSTANCES = ["Heroine", "Cocaine", "Methamphetamine", "Amphetamine", "MDMA", "XLR-11", "Ketamine",
              "cần sa", "thuốc phiện", "côca"]
CLAUSE_START = re.compile(r"^(\d+)\.\s", re.MULTILINE)
FOOTNOTE = re.compile(r"\[\d+\]")

def load_markdown_docs(folder: str | Path) -> list[Document]:
    """Read crawler output (.md with a flat `key: "value"` front matter) into Documents."""
    docs = []
    for path in sorted(Path(folder).glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        _, front, body = raw.split("---", 2)
        metadata = {k: json.loads(v) for k, v in re.findall(r'^(\w+): (".*")$', front, re.MULTILINE)}
        docs.append(Document(id=metadata.get("doc_id", path.stem), content=body.strip(), metadata=metadata))
    return docs

def normalize_crime(name: str) -> str:
    """'Tội Mua bán trái phép chất ma túy' -> 'mua bán trái phép chất ma túy'."""
    name = re.sub(r"\s+", " ", name.strip().strip("\"'“”").lower())
    return name.removeprefix("tội ").strip()

def link_entity(name: str, known: list[str], normalize: Callable[[str], str] = normalize_crime) -> str | None:
    """Map a free-text mention (e.g. a charge written by a journalist) onto one canonical name in `known`."""
    # TODO KG-1: normalize both sides, exact match first, then difflib.get_close_matches(cutoff=0.8).
    #            Return the ORIGINAL spelling from `known`; return None when nothing is close enough.
    # raise NotImplementedError("TODO KG-1 link_entity (src/graph.py) - kiểm tra: pytest tests/test_graph.py -k LinkEntity")

    # normalize là hàm chuẩn hóa có thể thay thế cho loại entity khác.
    normalized_name = normalize(name)
    # Không có tên cần tìm hoặc danh mục đối chiếu thì không tạo liên kết.
    if not normalized_name or not known:
        return None

    # Chuẩn hóa cả danh mục để so sánh công bằng, nhưng giữ known nguyên vẹn.
    # Hai danh sách có cùng thứ tự: tìm vị trí trong bản chuẩn hóa rồi lấy tên gốc.
    normalized_known = [normalize(candidate) for candidate in known]
    # Ưu tiên khớp chính xác sau chuẩn hóa, ví dụ bỏ tiền tố "Tội" và chữ hoa.
    if normalized_name in normalized_known:
        return known[normalized_known.index(normalized_name)]

    # Nếu chưa khớp, tìm tối đa một tên gần nhất (n=1), với độ giống >= 0.8.
    # Cách này hỗ trợ biến thể "ma tuý"/"ma túy"; điểm giống không phải xác suất đúng.
    matches = difflib.get_close_matches(normalized_name, normalized_known, n=1, cutoff=0.8)
    if matches:
        # Luôn trả phần tử gốc của known để hai KB dùng cùng tên node cầu nối.
        return known[normalized_known.index(matches[0])]
    # Không có ứng viên đạt ngưỡng: để trống liên kết thay vì tự đặt tên mới.
    return None

def find_substances(text: str) -> list[str]:
    lowered = text.lower()
    return [name for name in SUBSTANCES if name.lower() in lowered]

# ----------------------------------------------------------------------------------------------
# HINT — suggested ontology: extraction helpers
# ----------------------------------------------------------------------------------------------

def parse_law_article(doc: Document) -> dict[str, Any]:
    """Deterministic (regex) extraction for one 'Điều' — law text is regular enough to skip the LLM."""
    article_id = doc.metadata["article"]                       # "Điều 251 BLHS"
    title = doc.metadata["title"].split(". ", 1)[-1]           # "Tội mua bán trái phép chất ma túy"
    body = FOOTNOTE.sub("", doc.content)
    starts = list(CLAUSE_START.finditer(body))
    clauses = []
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(body)
        text = body[start.start():end].strip()
        first_line = text.splitlines()[0]
        penalty = re.search(r"\bbị ((?:phạt|tù|cảnh cáo).+?)(?::|$)", first_line)
        clauses.append({
            "id": f"{article_id} khoản {start.group(1)}",
            "number": int(start.group(1)),
            "penalty": penalty.group(1).rstrip(".") if penalty else "",
            "text": text,
            "substances": find_substances(text),
        })
    return {
        "id": article_id,
        "law": doc.metadata.get("law", ""),
        "title": title,
        "doc_id": doc.id,
        "crime": normalize_crime(title) if title.startswith("Tội ") else None,
        "clauses": clauses,
    }

NEWS_EXTRACTION_PROMPT = """Bạn trích xuất knowledge graph từ một bài báo tiếng Việt về ma túy.
Chỉ dùng thông tin có trong bài. Trả về JSON đúng dạng:
{{"cases": [{{
  "name": "tên ngắn của vụ việc, ví dụ: Vụ mua bán 36kg ma túy tại TP.HCM",
  "summary": "1-2 câu tóm tắt",
  "date": "ngày xảy ra/xét xử nếu có, dạng YYYY-MM-DD hoặc chuỗi rỗng",
  "location": "tỉnh/thành phố, chuỗi rỗng nếu không rõ",
  "charges": ["tội danh, BẮT BUỘC chọn đúng nguyên văn từ DANH SÁCH TỘI DANH"],
  "substances": [{{"name": "tên chất, dùng tên chuẩn trong DANH SÁCH CHẤT nếu khớp", "amount": "khối lượng nếu có"}}],
  "people": [{{"name": "họ tên", "aliases": ["biệt danh"], "role": "bị cáo|bị can|nghi phạm|người liên quan|cán bộ",
               "charge": "tội danh của người này (từ DANH SÁCH TỘI DANH) hoặc chuỗi rỗng",
               "sentence": "mức án nếu có, ví dụ: tử hình, 8 năm tù"}}]
}}]}}
Bài không nói về vụ việc cụ thể (tuyên truyền, hội nghị...) thì trả về {{"cases": []}}.

DANH SÁCH TỘI DANH: {crimes}
DANH SÁCH CHẤT: {substances}

Tiêu đề: {title}
Nội dung:
{content}"""

def extract_news_cases(doc: Document, llm_fn: Callable[[str], str], known_crimes: list[str]) -> list[dict]:
    """LLM extraction for one news article; charges are re-linked to law-KB crimes in code."""
    prompt = NEWS_EXTRACTION_PROMPT.format(
        crimes="; ".join(known_crimes), substances=", ".join(SUBSTANCES),
        title=doc.metadata.get("title", ""), content=doc.content[:12000],
    )
    try:
        cases = json.loads(llm_fn(prompt)).get("cases", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    for case in cases:
        case["charges"] = sorted({c for c in (link_entity(x, known_crimes) for x in case.get("charges", [])) if c})
        for person in case.get("people", []):
            person["charge"] = link_entity(person.get("charge") or "", known_crimes) or ""
    return cases

# ----------------------------------------------------------------------------------------------
# Neo4j
# ----------------------------------------------------------------------------------------------

class Neo4jGraph:
    """Thin wrapper over the official neo4j driver."""

    def __init__(self, uri: str, user: str, password: str) -> None:
        from neo4j import GraphDatabase

        self.driver = GraphDatabase.driver(uri, auth=(user, password), notifications_min_severity="OFF")
        self.driver.verify_connectivity()

    def close(self) -> None:
        self.driver.close()

    def run(self, cypher: str, **params: Any) -> list[dict]:
        records, _, _ = self.driver.execute_query(cypher, params)
        return [record.data() for record in records]

    def reset(self) -> None:
        """Delete every node, relationship and constraint (bench_kg.py calls this before build_graph)."""
        self.run("MATCH (n) DETACH DELETE n")
        for row in self.run("SHOW CONSTRAINTS YIELD name RETURN name"):
            self.run(f"DROP CONSTRAINT `{row['name']}` IF EXISTS")

    def stats(self) -> dict[str, int]:
        nodes = self.run("MATCH (n) RETURN count(n) AS n")[0]["n"]
        rels = self.run("MATCH ()-[r]->() RETURN count(r) AS n")[0]["n"]
        return {"nodes": nodes, "relationships": rels}

    def seed_facts(self, question: str, doc_ids: list[str], skip_labels: tuple[str, ...] = (),
                   limit: int = 60) -> tuple[list[str], list[str]]:
        """Ontology-independent first step: seed nodes + their 1-hop edges as text facts.

        Seeds = nodes whose `doc_id` is in doc_ids, or whose `name`/`aliases` appear in the question.
        Returns (seed elementIds, facts). Nodes with a label in skip_labels are left out of the facts.
        """
        seeds = self.run(
            """
            MATCH (n)
            WHERE n.doc_id IN $doc_ids
               OR (n.name IS :: STRING AND size(n.name) >= 3 AND toLower($q) CONTAINS toLower(n.name))
               OR any(a IN coalesce(n.aliases, []) WHERE size(a) >= 3 AND toLower($q) CONTAINS toLower(a))
            RETURN elementId(n) AS id
            """,
            q=question, doc_ids=doc_ids,
        )
        seed_ids = [row["id"] for row in seeds]
        edges = self.run(
            """
            MATCH (s)-[r]-(m)
            WHERE elementId(s) IN $ids
              AND none(l IN labels(s) + labels(m) WHERE l IN $skip)
            WITH DISTINCT r LIMIT $limit
            WITH startNode(r) AS a, r, endNode(r) AS b
            RETURN labels(a)[0] AS a_label, coalesce(a.name, a.id) AS a_name, type(r) AS rel,
                   properties(r) AS props, labels(b)[0] AS b_label, coalesce(b.name, b.id) AS b_name
            """,
            ids=seed_ids, skip=list(skip_labels), limit=limit,
        )
        facts = []
        for e in edges:
            props = ", ".join(f"{k}: {v}" for k, v in e["props"].items() if v)
            facts.append(f"({e['a_label']}: {e['a_name']}) -[{e['rel']}{' {' + props + '}' if props else ''}]-> "
                         f"({e['b_label']}: {e['b_name']})")
        return seed_ids, facts

    # ---------------------------------------------------------------- HINT — suggested ontology: writes

    def suggested_constraints(self) -> None:
        for label, key in [("Article", "id"), ("Clause", "id"), ("Crime", "name"), ("Case", "name"),
                           ("Substance", "name"), ("Person", "name"), ("Location", "name")]:
            self.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.{key} IS UNIQUE")

    def add_law_article(self, article: dict) -> None:
        self.run(
            """
            MERGE (a:Article {id: $id}) SET a.title = $title, a.law = $law, a.doc_id = $doc_id
            FOREACH (crime IN CASE WHEN $crime IS NULL THEN [] ELSE [$crime] END |
                MERGE (c:Crime {name: crime}) MERGE (a)-[:DEFINES]->(c))
            WITH a
            UNWIND $clauses AS clause
            MERGE (cl:Clause {id: clause.id})
              SET cl.number = clause.number, cl.penalty = clause.penalty, cl.text = clause.text, cl.doc_id = $doc_id
            MERGE (a)-[:HAS_CLAUSE]->(cl)
            FOREACH (s IN clause.substances | MERGE (sub:Substance {name: s}) MERGE (cl)-[:MENTIONS]->(sub))
            """,
            **article,
        )

    def add_news_case(self, case: dict, doc: Document) -> None:
        self.run(
            """
            MERGE (k:Case {name: $name})
              SET k.summary = $summary, k.date = $date, k.doc_id = $doc_id, k.source_title = $title
            FOREACH (loc IN CASE WHEN $location = '' THEN [] ELSE [$location] END |
                MERGE (l:Location {name: loc}) MERGE (k)-[:LOCATED_IN]->(l))
            FOREACH (crime IN $charges | MERGE (c:Crime {name: crime}) MERGE (k)-[:CHARGED_WITH]->(c))
            FOREACH (s IN $substances | MERGE (sub:Substance {name: s.name}) MERGE (k)-[r:INVOLVES]->(sub)
                SET r.amount = s.amount)
            FOREACH (p IN $people | MERGE (person:Person {name: p.name})
                SET person.aliases = coalesce(p.aliases, [])
                MERGE (person)-[r:INVOLVED_IN]->(k) SET r.role = p.role, r.charge = p.charge, r.sentence = p.sentence)
            """,
            name=case.get("name") or doc.metadata.get("title", doc.id),
            summary=case.get("summary", ""), date=case.get("date", ""), location=case.get("location", ""),
            charges=case.get("charges", []), people=[p for p in case.get("people", []) if p.get("name")],
            substances=[s for s in case.get("substances", []) if s.get("name")],
            doc_id=doc.id, title=doc.metadata.get("title", ""),
        )

    # ---------------------------------------------------------------- KG-3

    def context(self, question: str, doc_ids: list[str], max_facts: int = 60) -> list[str]:
        """Graph facts for a question: seeds + 1 hop, then the legal basis of every case reached."""
        # TODO KG-3: multi-hop retrieval over YOUR ontology.
        #   1. self.seed_facts(question, doc_ids) -> (seed_ids, facts)   (ontology-independent, already written)
        #   2. From the seeds, walk to the other KB through your bridge node (Cypher, see LAB_GUIDE Bước 5)
        #   3. Append one readable string per fact; return the list.
        #
        # HINT (suggested ontology):
        #   a. Cases that are a seed or next to one -> add f"Vụ việc '{name}': {summary}" to facts
        #        MATCH (k:Case) WHERE elementId(k) IN $ids OR EXISTS { MATCH (s)--(k) WHERE elementId(s) IN $ids }
        #   b. For those cases follow
        #        (Case)-[:CHARGED_WITH]->(Crime)<-[:DEFINES]-(Article)-[:HAS_CLAUSE]->(Clause)
        #      keep clause 1 + clauses that MENTION a Substance the case INVOLVES
        #   c. Articles named in the question ("Điều 251" -> re.findall(r"[Đđ]iều (\d+)", question)):
        #      clause 1 + clauses mentioning find_substances(question)
        #   d. One fact per clause: f"[{article_id} - {title}] khoản {number}: {text}"
        # raise NotImplementedError("TODO KG-3 Neo4jGraph.context (src/graph.py) - kiểm tra: python bench_kg.py --check")
        if max_facts <= 0:
            return []

        # Bước 5: seed lấy từ doc_id của vector search hoặc tên/biệt danh trong câu hỏi.
        # Dữ kiện 1-hop chưa chứa nội dung khoản luật, nên cần truy vấn mở rộng bên dưới.
        seed_ids, seed_facts = self.seed_facts(question, doc_ids, limit=max_facts)
        substances = find_substances(question)
        article_numbers = re.findall(r"\bđiều\s+(\d+)\b", question, flags=re.IGNORECASE)
        wants_maximum = bool(re.search(r"tối đa|cao nhất", question, flags=re.IGNORECASE))
        aggregate_cases = bool(substances and re.search(
            r"(?:những|các)\s+vụ|liệt kê.*vụ", question, flags=re.IGNORECASE))

        # Nếu hỏi một người cụ thể, ưu tiên vụ của người đó thay vì mọi vụ kề
        # Substance/Crime dùng chung. Aliases giúp tìm người qua tên như Hoàng Nato.
        people = self.run(
            """
            MATCH (p:Person)
            WHERE (size(p.name) >= 3 AND toLower($q) CONTAINS toLower(p.name))
               OR any(alias IN coalesce(p.aliases, [])
                      WHERE size(alias) >= 3 AND toLower($q) CONTAINS toLower(alias))
            RETURN elementId(p) AS id
            """,
            q=question,
        )
        person_ids = [person["id"] for person in people]
        cases = self.run(
            """
            MATCH (k:Case)
            WHERE ($aggregate AND EXISTS {
                MATCH (k)-[:INVOLVES]->(s:Substance) WHERE s.name IN $substances
            }) OR (NOT $aggregate AND (size($article_numbers) = 0 OR size($person_ids) > 0) AND (
                (size($person_ids) > 0 AND EXISTS {
                    MATCH (p:Person)-[:INVOLVED_IN]->(k) WHERE elementId(p) IN $person_ids
                }) OR (size($person_ids) = 0 AND (
                    elementId(k) IN $ids OR EXISTS {
                        MATCH (seed)--(k) WHERE elementId(seed) IN $ids
                    }
                ))
            ))
            OPTIONAL MATCH (p:Person)-[r:INVOLVED_IN]->(k)
            WITH k, collect(DISTINCT {name: p.name, role: r.role,
                                     charge: r.charge, sentence: r.sentence}) AS people
            OPTIONAL MATCH (k)-[i:INVOLVES]->(s:Substance)
            RETURN elementId(k) AS id, k.name AS name, k.summary AS summary,
                   k.doc_id AS doc_id, k.date AS date, people,
                   collect(DISTINCT {name: s.name, amount: i.amount}) AS substances
            ORDER BY doc_id, name
            """,
            aggregate=aggregate_cases, substances=substances, person_ids=person_ids,
            ids=seed_ids, article_numbers=article_numbers,
        )
        case_ids = [case["id"] for case in cases]
        case_facts = []
        for case in cases:
            # Giữ mức án và tội danh trên từng người, không gán án chung cho cả vụ.
            details = [f"[{case['doc_id']}] Vụ việc '{case['name']}': {case['summary'] or ''}"]
            if case["date"]:
                details.append(f"Ngày: {case['date']}")
            for person in case["people"]:
                if person["name"]:
                    attributes = [f"{key}: {person[key]}" for key in ("role", "charge", "sentence")
                                  if person[key]]
                    details.append(f"{person['name']} ({'; '.join(attributes)})")
            for substance in case["substances"]:
                if substance["name"]:
                    details.append(f"Chất: {substance['name']}; lượng: {substance['amount'] or 'không rõ'}")
            case_facts.append(" | ".join(details))

        # Đi xuyên KB qua Crime, rồi chọn khoản 1 và các khoản nhắc chất của vụ.
        # Khi đã nhận diện người, chỉ lấy tội trùng INVOLVED_IN.charge của người đó.
        # Câu hỏi mức tối đa cần toàn bộ khoản: khoản cuối có thể chỉ là phạt bổ sung.
        # Nhánh còn lại lấy Điều được gọi tên hoặc luật trong seed; các Điều không
        # định nghĩa tội (như giải thích từ ngữ) cần cả nội dung khoản ngoài khoản 1.
        clauses = [] if aggregate_cases else self.run(
            """
            MATCH (a:Article)-[:HAS_CLAUSE]->(cl:Clause)
            WHERE EXISTS {
                MATCH (k:Case)-[:CHARGED_WITH]->(c:Crime)<-[:DEFINES]-(a)
                WHERE elementId(k) IN $case_ids
                  AND (size($person_ids) = 0 OR EXISTS {
                      MATCH (p:Person)-[r:INVOLVED_IN]->(k)
                      WHERE elementId(p) IN $person_ids AND r.charge = c.name
                  })
                  AND ($maximum OR cl.number = 1 OR EXISTS {
                      MATCH (k)-[:INVOLVES]->(:Substance)<-[:MENTIONS]-(cl)
                  })
            } OR (
                (split(a.id, ' ')[1] IN $article_numbers
                 OR (size($article_numbers) = 0 AND size($person_ids) = 0 AND
                     (elementId(a) IN $ids OR elementId(cl) IN $ids)))
                AND ($maximum OR cl.number = 1
                     OR NOT EXISTS { MATCH (a)-[:DEFINES]->(:Crime) }
                     OR EXISTS {
                         MATCH (cl)-[:MENTIONS]->(s:Substance) WHERE s.name IN $substances
                     })
            )
            RETURN DISTINCT a.id AS article_id, a.title AS title,
                            cl.number AS number, cl.text AS text
            ORDER BY article_id, number
            """,
            case_ids=case_ids, person_ids=person_ids, maximum=wants_maximum,
            article_numbers=article_numbers, ids=seed_ids, substances=substances,
        )
        # Đưa định nghĩa đúng thuật ngữ lên trước các khoản khác khi giới hạn context.
        # Ví dụ "4. Tiền chất là ..." cho khóa "tiền chất"; không hard-code số khoản.
        def clause_priority(clause: dict) -> int:
            text = re.sub(r"\s+", " ", clause["text"]).lower()
            definition = re.match(r"^\d+\.\s+(.+?)\s+là\s", text)
            return 0 if definition and definition.group(1) in question.lower() else 1

        clauses.sort(key=clause_priority)
        law_facts = [f"[{cl['article_id']} - {cl['title']}] khoản {cl['number']}: {cl['text']}"
                     for cl in clauses]
        # Ưu tiên nội dung luật và vụ việc trước cạnh seed để dữ kiện multi-hop không
        # bị mất chỉ vì seed đã đầy. dict giữ thứ tự và loại dòng trùng trước khi cắt.
        return list(dict.fromkeys(law_facts + case_facts + seed_facts))[:max_facts]

# ---------------------------------------------------------------------------------------------- KG-2

def build_graph(graph: Neo4jGraph, law_docs: list[Document], news_docs: list[Document],
                llm_fn: Callable[..., str]) -> None:
    """Load both KBs into an empty graph. llm_fn(prompt, json_mode=False) -> str (metered OpenAI chat)."""
    # TODO KG-2: create YOUR ontology in Neo4j from both KBs.
    #   Contract: every node created from one document has the property doc_id = Document.id.
    #   Fastest start: the HINT helpers above (parse_law_article, extract_news_cases, suggested_constraints,
    #   add_law_article, add_news_case). Own ontology + report/ONTOLOGY.md = bonus (SUBMISSION.md).
    # raise NotImplementedError("TODO KG-2 build_graph (src/graph.py) - kiểm tra: python bench_kg.py --build --limit 2")

    # Bước 4 (KG-2): bên gọi đã làm rỗng graph, nên hàm này không gọi reset().
    # Tạo ràng buộc duy nhất theo khóa của 7 label trước khi MERGE dữ liệu.
    # Ràng buộc tránh trùng khóa, chưa tự nhận biết hai tên khác nhau là cùng thực thể.
    graph.suggested_constraints()

    # Nạp luật trước để có danh sách tội danh chuẩn làm cầu nối giữa hai KB.
    # Mỗi Document luật được regex tách thành Điều, các khoản và chất được nhắc;
    # phần này không gọi LLM. Kết quả là các dict mà add_law_article nhận vào.
    articles = [parse_law_article(doc) for doc in law_docs]
    for article in articles:
        # Ghi Article, Clause, Crime, Substance cùng các cạnh tương ứng.
        # Article và Clause giữ doc_id của tài liệu luật để truy ngược nguồn.
        graph.add_law_article(article)
    # Bỏ các Điều không định nghĩa tội (crime=None), dùng set loại tên trùng,
    # rồi sorted để danh mục đưa vào prompt có thứ tự ổn định.
    crimes = sorted({article["crime"] for article in articles if article["crime"]})

    # Trích tin ở chế độ JSON; helper liên kết tội danh và lưu doc_id của bài.
    for doc in news_docs:
        # lambda chuyển hàm chỉ nhận prompt thành lời gọi llm_fn có json_mode=True.
        # extract_news_cases đưa crimes vào prompt, đọc JSON và gọi link_entity
        # để đối chiếu tội danh của vụ/người với danh mục chuẩn đã lấy từ luật.
        cases = extract_news_cases(doc, lambda prompt: llm_fn(prompt, json_mode=True), crimes)
        # Một bài có thể cho nhiều vụ; danh sách rỗng thì không ghi vụ nào.
        for case in cases:
            # Ghi Case, người, chất, địa điểm và các cạnh; Case giữ doc.id.
            # Crime dùng chung tạo đường Case -> Crime <- Article giữa hai KB.
            graph.add_news_case(case, doc)

# ---------------------------------------------------------------------------------------------- KG-4

GRAPH_PROMPT = """Trả lời câu hỏi chỉ dựa trên ngữ cảnh (đoạn văn bản và dữ kiện từ knowledge graph).
Nêu rõ số Điều luật khi có. Nếu ngữ cảnh không đủ, nói không đủ thông tin.

Dữ kiện knowledge graph:
{facts}

Đoạn văn bản:
{chunks}

Câu hỏi: {question}
Trả lời:"""

class GraphRAGAgent:
    """Hybrid GraphRAG: the same vector top-k as flat RAG, plus facts expanded from the graph."""

    def __init__(self, store: EmbeddingStore, graph: Neo4jGraph, llm_fn: Callable[[str], str]) -> None:
        self.store = store
        self.graph = graph
        self.llm_fn = llm_fn

    def answer(self, question: str, top_k: int = 3) -> str:
        # TODO KG-4: vector top-k (same as flat RAG) -> doc_ids of the hits -> self.graph.context(question, doc_ids)
        #            -> fill GRAPH_PROMPT -> self.llm_fn(prompt)
        # raise NotImplementedError("TODO KG-4 GraphRAGAgent.answer (src/graph.py) - kiểm tra: pytest tests/test_graph.py -k GraphRAGAgent")
        # Bước 6: lấy cùng top-k đoạn văn như Flat RAG để giữ ngữ cảnh từ vector search.
        chunks = self.store.search(question, top_k=top_k)

        # Nhiều chunk có thể thuộc cùng tài liệu; loại doc_id trùng nhưng giữ thứ tự.
        # Dùng ID tài liệu gốc trong metadata, không dùng ID riêng của từng chunk.
        doc_ids = list(dict.fromkeys(chunk["metadata"]["doc_id"] for chunk in chunks))
        facts = self.graph.context(question, doc_ids)

        # Bổ sung dữ kiện multi-hop bên cạnh các đoạn gốc, rồi điền câu hỏi vào prompt.
        # Ngay cả khi không tìm được chunk, graph vẫn có thể tìm qua tên/biệt danh.
        prompt = GRAPH_PROMPT.format(
            facts="\n".join(f"- {fact}" for fact in facts),
            chunks="\n\n".join(f"[{i}] {chunk['content']}" for i, chunk in enumerate(chunks, start=1)),
            question=question,
        )
        return self.llm_fn(prompt)
