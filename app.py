import streamlit as st
import requests
import re
import urllib.parse
from google import genai
from google.genai import types

st.set_page_config(
    page_title="AI 판례 직통 검색 & 요약 서비스",
    page_icon="⚖️",
    layout="wide"
)

st.title("⚖️ 핵심 키워드 기반 AI 판례 검색 & 요약")
st.caption("질문 속 핵심 단어를 포착하여 국가법령정보센터의 실제 관련 판례를 직접 찾아 요약합니다.")

# API 키 설정
gemini_key = ""
if hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
    gemini_key = st.secrets["GEMINI_API_KEY"]

if not gemini_key:
    gemini_key = st.sidebar.text_input("Gemini API Key를 입력하세요", type="password")

if not gemini_key:
    st.info("💡 Gemini API 키를 설정해 주세요.")
    st.stop()

client = genai.Client(api_key=gemini_key)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

def clean_html(text: str) -> str:
    if not text:
        return ""
    text = text.replace("<![CDATA[", "").replace("]]>", "")
    text = re.sub(r'<br\s*/?>', '\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()

# 판례 검색 함수: 본문(2)과 제목(1) 동시 탐색
def search_prec_list(keyword: str, display_count: int = 5):
    prec_list = []
    seen_ids = set()
    
    # 순수 한글/영문/숫자만 남김
    clean_kw = re.sub(r'[^가-힣a-zA-Z0-9]', '', keyword)
    if not clean_kw:
        return []

    # 본문(search=2) 검색 우선, 없으면 제목(search=1)
    for scope in ["2", "1"]:
        encoded = urllib.parse.quote(clean_kw)
        url = f"http://www.law.go.kr/DRF/lawSearch.do?OC=test&target=prec&type=JSON&search={scope}&query={encoded}&display={display_count}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=8)
            data = resp.json()
            items = data.get("PrecSearch", {}).get("prec", [])
            if isinstance(items, dict):
                items = [items]
                
            for it in items:
                pid = str(it.get("판례일련번호", "")).strip()
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    prec_list.append({
                        "prec_id": pid,
                        "case_no": it.get("사건번호", "").strip(),
                        "case_name": it.get("사건명", "").strip(),
                        "court_name": it.get("법원명", "").strip(),
                        "judge_date": it.get("선고일자", "").strip()
                    })
        except Exception:
            continue
            
        if len(prec_list) >= display_count:
            break
            
    return prec_list

# 판례 본문 조회 함수
def get_prec_detail(prec_id: str):
    url = f"http://www.law.go.kr/DRF/lawService.do?OC=test&target=prec&ID={prec_id}&type=XML"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        resp.encoding = 'utf-8'
        text = resp.text
        
        def extract_tag(tag):
            m = re.search(rf'<{tag}>(.*?)</{tag}>', text, re.DOTALL)
            return clean_html(m.group(1)) if m else ""
            
        return {
            "holding": extract_tag("판시사항") or "판시사항 정보 없음",
            "summary": extract_tag("판결요지") or "판결요지 정보 없음",
            "reason": extract_tag("판결이유")[:2000]
        }
    except Exception:
        return {"holding": "", "summary": "", "reason": ""}

# 사용자 인터페이스
user_question = st.text_area(
    "💬 찾고 싶은 판례나 상황을 편하게 입력하세요:",
    placeholder="예: 자전거대 자전거 사고 판례를 보고 싶어 / 횡단보도 우회전 보행자 사고 판례 / 전세보증금 반환 거부 판례",
    height=100
)

if st.button("🔍 관련 판례 즉시 검색", type="primary", use_container_width=True):
    if not user_question.strip():
        st.warning("질문을 입력해 주세요.")
    else:
        with st.status("🔍 질문에서 판례 검색용 핵심 단어 추출 중...", expanded=True) as status:
            # 질문에서 '판례', '사고', '보고싶어' 같은 잉여어를 뺀 실질 검색어 3개 도출
            kw_prompt = f"""
            사용자의 질문에서 법제처 판례 데이터베이스 검색에 넣을 '가장 구체적인 핵심 실질 명사' 3개를 순서대로 추출하세요.
            
            [규칙]
            - '판례', '사례', '소송', '관련', '사고', '경우' 같은 일반적이거나 무의미한 단어는 절대 제외하세요.
            - 오직 구체적인 사물, 행위, 법률 대상 명사만 남기세요.
              예: "자전거대 자전거 사고 판례" -> 자전거, 충돌, 과실비율
              예: "아파트 윗집 누수 보상 판례" -> 누수, 하자, 손해배상
              예: "월세 계약 끝났는데 보증금 안줌" -> 임차보증금, 임대차, 대항력
            - 쉼표(,)로만 구분해서 3단어만 출력하세요.
            
            질문: {user_question}
            키워드:
            """
            kw_res = client.models.generate_content(model="gemini-3.5-flash-lite", contents=kw_prompt)
            raw_kws = kw_res.text.strip().replace('"', '').replace("'", "").replace(" ", "")
            keywords = [k.strip() for k in raw_kws.split(",") if k.strip()]
            
            st.write(f"🎯 캐치한 핵심 검색어: **{', '.join(keywords)}**")
            
            # 키워드로 판례 직접 수집
            st.write("🏛️ 국가법령정보센터에서 실제 판례 찾는 중...")
            all_precs = []
            seen_ids = set()
            hit_keyword = ""
            
            for kw in keywords:
                found = search_prec_list(kw, display_count=3)
                for f in found:
                    if f["prec_id"] not in seen_ids:
                        seen_ids.add(f["prec_id"])
                        all_precs.append(f)
                if len(all_precs) >= 3:
                    hit_keyword = kw
                    break
                    
            if not all_precs:
                status.update(label="판례 검색 실패", state="error")
                st.error("관련 판례를 찾지 못했습니다. 다른 핵심 단어로 입력해 보세요.")
                st.stop()

            prec_payload = []
            for p in all_precs[:3]:
                body = get_prec_detail(p["prec_id"])
                prec_payload.append({"meta": p, "content": body})
            
            st.write(f"✅ 판례 {len(prec_payload)}건 확보 완료")
            status.update(label="핵심 판례 수집 완료!", state="complete", expanded=False)

        # 판례 중심 분석 및 요약 리포트
        with st.spinner("⚖️ 판례 요약 보고서를 작성 중입니다..."):
            prec_text = ""
            for idx, item in enumerate(prec_payload, 1):
                m = item["meta"]
                c = item["content"]
                prec_text += f"""
[판례 #{idx}]
사건번호: {m['court_name']} {m['case_no']} ({m['case_name']}, {m['judge_date']} 선고)
판시사항: {c['holding']}
판결요지: {c['summary']}
판결이유(발췌): {c['reason']}
--------------------------------------------------
"""

            summary_prompt = f"""
            당신은 판례 전문 리서치 AI입니다.
            사용자의 질문: "{user_question}"
            
            수집된 [실제 판례 데이터]를 바탕으로, 불필요한 서론 없이 사용자가 궁금해하는 판례 핵심 내용을 보기 쉽게 정리하세요.
            
            [작성 양식]
            ## 📜 관련 핵심 판례 분석
            (수집된 판례 각각에 대해 아래 블록 작성)
            ### 🔹 {m['court_name']} [사건번호] - [사건명] ([선고일자] 선고)
            * **사건 개요 및 핵심 쟁점**: (어떤 상황에서 발생한 분쟁인지 1~2줄 요약)
            * **법원의 판단 기준(판결 요지)**: (법원이 누구의 손을 들어주었고, 과실이나 책임을 어떻게 판단했는지 2~3줄 요약)
            * **질문과의 연관 포인트**: (질문자가 알고 싶어 하는 상황에 이 판결이 주는 의미)
            
            ---
            ## 💡 요약 및 실무적 시사점
            - 위 판례들이 공통적으로 제시하는 판단 기준(예: 과실비율 산정 시 주시의무, 안전거리 확보 여부 등)
            - 질문 상황에서 참고해야 할 핵심 포인트
            
            [실제 판례 데이터]:
            {prec_text}
            """
            
            res = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=summary_prompt,
                config=types.GenerateContentConfig(temperature=0.2)
            )

        st.markdown(res.text)

        with st.expander("🔎 수집된 실제 판례 원문(판시사항·판결요지) 확인"):
            for item in prec_payload:
                m = item["meta"]
                c = item["content"]
                st.markdown(f"#### 🏛️️ {m['court_name']} {m['case_no']} ({m['case_name']})")
                st.markdown(f"**선고일자:** {m['judge_date']}")
                st.markdown(f"**【판시사항】**\n\n{c['holding']}")
                st.markdown(f"**【판결요지】**\n\n{c['summary']}")
                st.divider()
