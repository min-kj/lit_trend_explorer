# -*- coding: utf-8 -*-
"""
동향 발견 분석 — 초록 토픽모델링(LDA) · rising terms(TF-IDF) · 공동등장 네트워크/매트릭스.

OpenAlex Topic은 알고리즘 라벨이라 추상적이므로, 복원한 초록을 직접 LDA/TF-IDF로 세분화한다.
전부 비지도 통계(코드 집계)이지 LLM 추론이 아님 — 결과는 입력 코퍼스로 역추적 가능.
Streamlit Cloud 메모리 보호용으로 문서 수를 캡한다.
"""
try:
    import numpy as np
    from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
    from sklearn.decomposition import LatentDirichletAllocation
    HAS_SKLEARN = True
except Exception:
    HAS_SKLEARN = False

try:
    import networkx as nx
    HAS_NX = True
except Exception:
    HAS_NX = False

# 학술 초록 흔한 불용어(영어 stopwords에 추가)
EXTRA_STOP = [
    "study", "studies", "paper", "article", "research", "results", "result",
    "using", "used", "use", "based", "analysis", "data", "method", "methods",
    "approach", "findings", "propose", "proposed", "show", "shows", "shown",
    "presents", "present", "novel", "new", "model", "models", "also", "however",
    "thus", "therefore", "may", "can", "could", "two", "one", "three",
]


def _clean_corpus(abstracts, max_docs):
    docs = [a for a in abstracts if a and len(a.split()) >= 10]
    return docs[:max_docs]


def _stopwords():
    try:
        from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
        return list(ENGLISH_STOP_WORDS.union(EXTRA_STOP))
    except Exception:
        return "english"


# ============================================================
# 1) LDA 토픽모델링
# ============================================================
def topic_model(abstracts, n_topics=8, n_top_words=10, max_docs=2000):
    """
    초록 리스트 -> [{'topic': i, 'words': [..], 'size': 문서수}], used_docs.
    (ok, data|err) 형태가 아니라 (topics, info) 반환. 부족하면 topics=[].
    """
    if not HAS_SKLEARN:
        return [], {"error": "scikit-learn 미설치 (requirements 확인)"}
    docs = _clean_corpus(abstracts, max_docs)
    if len(docs) < 20:
        return [], {"error": f"초록이 부족합니다(유효 {len(docs)}건, 최소 20건). 검색 범위를 넓히거나 '전체 본문'으로."}
    n_topics = max(2, min(n_topics, 15))
    vec = CountVectorizer(stop_words=_stopwords(), max_df=0.85, min_df=3,
                          max_features=1500, ngram_range=(1, 2))
    try:
        X = vec.fit_transform(docs)
    except ValueError as e:
        return [], {"error": f"벡터화 실패: {e}"}
    if X.shape[1] < n_topics:
        return [], {"error": "어휘가 너무 적습니다."}
    lda = LatentDirichletAllocation(n_components=n_topics, random_state=42,
                                    max_iter=15, learning_method="batch")
    doc_topic = lda.fit_transform(X)
    vocab = vec.get_feature_names_out()
    dominant = doc_topic.argmax(axis=1)
    topics = []
    for i, comp in enumerate(lda.components_):
        top_idx = comp.argsort()[::-1][:n_top_words]
        topics.append({
            "topic": i + 1,
            "words": [vocab[j] for j in top_idx],
            "size": int((dominant == i).sum()),
        })
    topics.sort(key=lambda t: t["size"], reverse=True)
    return topics, {"used_docs": len(docs), "vocab": X.shape[1]}


# ============================================================
# 1b) 최적 토픽 수(k) 추천 — perplexity + UMass coherence sweep
#     (임의 k 대신 정량 지표로 근거를 남기기 위한 보조)
# ============================================================
def _umass_coherence(components, Xb, doc_freq, topn=10):
    """UMass coherence(평균). 0에 가까울수록(덜 음수일수록) 응집도 높음."""
    Xb = Xb.tocsc()
    cohs = []
    for comp in components:
        top = comp.argsort()[::-1][:topn]
        s, cnt = 0.0, 0
        for i in range(1, len(top)):
            for j in range(i):
                wi, wj = top[i], top[j]
                co = int(Xb[:, wi].multiply(Xb[:, wj]).sum())
                s += np.log((co + 1.0) / max(int(doc_freq[wj]), 1))
                cnt += 1
        if cnt:
            cohs.append(s / cnt)
    return float(np.mean(cohs)) if cohs else float("nan")


def suggest_k(abstracts, k_min=2, k_max=10, max_docs=1500):
    """
    k=k_min..k_max 를 쓸어 각 k의 perplexity·coherence 계산.
    (data|None, err). best_coherence = coherence 최대 k.
    클라우드 보호: 문서·반복 제한.
    """
    if not HAS_SKLEARN:
        return None, "scikit-learn 미설치"
    docs = _clean_corpus(abstracts, max_docs)
    if len(docs) < 30:
        return None, f"초록 부족(유효 {len(docs)}건, 최소 30건). 검색을 넓히세요."
    vec = CountVectorizer(stop_words=_stopwords(), max_df=0.85, min_df=3,
                          max_features=1200, ngram_range=(1, 2))
    try:
        X = vec.fit_transform(docs)
    except ValueError as e:
        return None, f"벡터화 실패: {e}"
    Xb = (X > 0)
    doc_freq = np.asarray(Xb.sum(axis=0)).ravel()
    rows = []
    for k in range(k_min, min(k_max, max(2, X.shape[1] - 1)) + 1):
        lda = LatentDirichletAllocation(n_components=k, random_state=42,
                                        max_iter=10, learning_method="batch")
        lda.fit(X)
        rows.append({
            "k": k,
            "perplexity": float(lda.perplexity(X)),
            "coherence": _umass_coherence(lda.components_, Xb, doc_freq),
        })
    if not rows:
        return None, "어휘 부족"
    best = max(rows, key=lambda r: r["coherence"])["k"]
    return {"rows": rows, "best_coherence": best, "used_docs": len(docs)}, None


# ============================================================
# 2) Rising terms (cutoff 전후 TF-IDF 차이)
# ============================================================
def rising_terms(records, cutoff_year, top=20, max_docs=4000):
    """
    cutoff_year 전/후 초록의 평균 TF-IDF 차이로 '뜨는 용어'·'지는 용어'.
    -> {'rising': [(term, delta, before, after)], 'falling': [...], info}
    """
    if not HAS_SKLEARN:
        return {"error": "scikit-learn 미설치"}
    before, after = [], []
    for r in records:
        a = r.get("abstract_clean") or r.get("abstract") or ""
        if not a or len(a.split()) < 10:
            continue
        y = r.get("year")
        if not y:
            continue
        (before if y < cutoff_year else after).append(a)
    before, after = before[:max_docs], after[:max_docs]
    if len(before) < 10 or len(after) < 10:
        return {"error": f"전/후 표본 부족 (전 {len(before)}·후 {len(after)}건, 각 10건 이상 필요). cutoff 연도를 조정하세요."}
    vec = TfidfVectorizer(stop_words=_stopwords(), max_df=0.85, min_df=3,
                          max_features=2000, ngram_range=(1, 2))
    X = vec.fit_transform(before + after)
    vocab = vec.get_feature_names_out()
    nb = len(before)
    mean_b = X[:nb].mean(axis=0).A1
    mean_a = X[nb:].mean(axis=0).A1
    delta = mean_a - mean_b
    order = delta.argsort()
    falling = [(vocab[j], float(delta[j]), float(mean_b[j]), float(mean_a[j])) for j in order[:top]]
    rising = [(vocab[j], float(delta[j]), float(mean_b[j]), float(mean_a[j])) for j in order[::-1][:top]]
    return {"rising": rising, "falling": falling,
            "info": {"before": nb, "after": len(after), "cutoff": cutoff_year}}


# ============================================================
# 3) 국가 공동등장(공저) 매트릭스
# ============================================================
def country_cooccurrence(records, top=12):
    """
    레코드별 국가코드 집합 -> 상위 N개국 공동등장(공저) 매트릭스.
    -> {'labels': [..], 'matrix': [[..]], 'singles': [(cc, n)]}
    """
    from collections import Counter
    freq = Counter()
    pair = Counter()
    for r in records:
        ccs = sorted(set(r.get("countries") or []))
        for c in ccs:
            freq[c] += 1
        for i in range(len(ccs)):
            for j in range(i + 1, len(ccs)):
                pair[(ccs[i], ccs[j])] += 1
    labels = [c for c, _ in freq.most_common(top)]
    idx = {c: i for i, c in enumerate(labels)}
    n = len(labels)
    matrix = [[0] * n for _ in range(n)]
    for (a, b), c in pair.items():
        if a in idx and b in idx:
            matrix[idx[a]][idx[b]] = c
            matrix[idx[b]][idx[a]] = c
    for c in labels:
        matrix[idx[c]][idx[c]] = freq[c]  # 대각선 = 단독 등장 수
    return {"labels": labels, "matrix": matrix,
            "singles": freq.most_common(top)}


# ============================================================
# 3b) 분수계수(fractional count) — 공저 부풀림 보정
#     논문 1편의 크레딧 1을 참여 엔티티 수로 나눠 합산. (full 은 group_by 가 줌)
# ============================================================
def fractional_counts(records, field="countries", top=15):
    """records 의 (authors|institutions|countries) 를 1/n 가중 합산. [(label, 점수, '')...]."""
    from collections import defaultdict
    score = defaultdict(float)
    for r in records:
        items = list({x for x in (r.get(field) or []) if x})
        if not items:
            continue
        w = 1.0 / len(items)
        for x in items:
            score[x] += w
    rows = sorted(score.items(), key=lambda kv: kv[1], reverse=True)
    return [(lbl, round(v, 2), "") for lbl, v in rows[:top]]


# ============================================================
# 4) 공동등장 네트워크 (공저자 / 기관 / 국가) — networkx + spring layout
# ============================================================
_NET_FIELD = {"coauthor": "authors", "institution": "institutions", "country": "countries"}


def cooccurrence_network(records, mode="coauthor", top_n=25, max_records=1500, max_per_record=30):
    """
    records 의 (저자|기관|국가) 동시등장 → 상위 top_n 노드 네트워크.
    (data|None, err). data = {nodes:[{id,x,y,size}], edges:[{x0,y0,x1,y1,w}], mode}
    max_per_record: 저자 수 많은 논문(거대 클리크)은 페어링 스킵(빈도만 카운트).
    """
    if not HAS_NX:
        return None, "networkx 미설치 (requirements 확인)"
    from collections import Counter
    field = _NET_FIELD.get(mode, "authors")
    freq, pair = Counter(), Counter()
    for r in records[:max_records]:
        items = sorted({x for x in (r.get(field) or []) if x})
        for x in items:
            freq[x] += 1
        if len(items) > max_per_record:
            continue  # 거대 저자 논문은 페어링 제외(빈도는 유지)
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                pair[(items[i], items[j])] += 1
    top = [x for x, _ in freq.most_common(top_n)]
    tset = set(top)
    if len(top) < 2:
        return None, "노드가 부족합니다(2개 미만). 검색 범위를 넓히세요."
    G = nx.Graph()
    for x in top:
        G.add_node(x, size=freq[x])
    for (a, b), w in pair.items():
        if a in tset and b in tset:
            G.add_edge(a, b, weight=w)
    pos = nx.spring_layout(G, seed=42, k=0.6)
    nodes = [{"id": x, "x": float(pos[x][0]), "y": float(pos[x][1]), "size": freq[x]}
             for x in G.nodes]
    edges = [{"x0": float(pos[a][0]), "y0": float(pos[a][1]),
              "x1": float(pos[b][0]), "y1": float(pos[b][1]), "w": d["weight"]}
             for a, b, d in G.edges(data=True)]
    return {"nodes": nodes, "edges": edges, "mode": mode,
            "n_edges": len(edges)}, None
