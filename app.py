import streamlit as st
import requests
import json
from google import genai
from google.genai import types

# ----------------- 페이지 기본 설정 -----------------
st.set_page_config(
    page_title="AI 판례 분석 어시스턴트",
    page_icon="⚖️",
    layout="centered"
)

st.title("⚖️ AI 판례 기반 법률 어시스턴트")
st.caption("국가법령정보센터 실제 대법원 판례를 실시간으로 검색하여 법률 분석을 제공합니다.")

# ----------------- API 키 로드 -----------------
# 1순위: Streamlit Secrets에 등록된 키
# 2순위: 등록되지 않았을 경우 사이드바에서 직접 입력
gemini_key = ""
if hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
    gemini_key = st.secrets["GEMINI_API_KEY"]

if not gemini_key:
    gemini_key = st.sidebar.text_input("Gemini API Key를 입력하세요", type="password")

if not gemini_key:
    st.info("💡 사이드바(좌측 화살표)에 Gemini API 키를 입력하거나 Secrets 설정을 완료해 주세요.")
    st.stop()

# Gemini 클라이언트 초기화
client = genai.Client(api_key=gemini_key)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# ----------------- 법제처 판례 수집 함수 -----------------
def search_prec_list(query: str, display_count: int = 3):
    url = "http://www.law.go.kr/DRF/lawSearch.do"
    params = {
        "OC": "test",
        "target": "prec",
        "type": "JSON",
        "query": query,
        "display": display_count
    }
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = resp.json()
        prec_data = data.get("PrecSearch", {}).get("prec", [])
        if isinstance(prec_data, dict):
            prec_data = [prec_data]
            
        prec_list = []
        for item in prec_data:
            pid = item.get("판례일련번호")
            if pid:
                prec_list.append({
                    "prec_id": str(pid),
                    "case_no": item.get("사건번호", ""),
                    "case_name": item.get("사건명", ""),
                    "court_name": item.get("법원명", ""),
                    "judge_date": item.get("선고일자", "")
                })
        return prec_list
    except Exception:
        return []

def get_prec_detail(prec_id: str):
    url = "http://www.law.go.kr/DRF/lawService.do"
    params = {
        "OC": "test",
        "target": "prec",
        "ID": prec_id,
        "type": "JSON"
    }
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        detail = resp.json().get("PrecService", {})
    except Exception:
        return ""
    
    return f"""
[판례 정보]
- 사건명: {detail.get("사건명", "")}
- 사건번호: {detail.get("사건번호", "")} ({detail.get("법원명", "")}, {detail.get("선고일자", "")} 선고)
- 판시사항:
{detail.get("판시사항", "내용 없음")}

- 판결요지:
{detail.get("판결요지", "내용 없음")}

- 판결이유(발췌):
{str(detail.get("판결이유", ""))[:2500]}
--------------------------------------------------
"""

# ----------------- 웹 화면 입력 UI -----------------
user_question = st.text_area(
    "질문이나 상담하고 싶은 법률 상황을 입력하세요:",
    placeholder="예: 임대차 계약이 끝났는데 보증금을 못 받은 상태에서 집주인이 집을 팔았어. 새 집주인한테 보증금 돌려달라고 할 수 있어?",
    height=120
)

if st.button("판례 검색 및 AI 분석 시작", type="primary", use_container_width=True):
    if not user_question.strip():
        st.warning("질문을 입력해 주세요.")
    else:
        with st.spinner("1단계: 핵심 법률 키워드를 추출하는 중..."):
            kw_prompt = f"""
            사용자의 법률 질문에서 판례 검색 사이트에 넣을 가장 핵심적인 단일 법률 명사 단 하나(띄어쓰기 금지, 2~5글자)를 추출하세요.
            예: 임차보증금, 대항력, 주택임대차, 권리금, 부당해고
            부가 설명 없이 단어만 출력하세요.
            
            질문: {user_question}
            검색어:
            """
            kw_res = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=kw_prompt
            )
            search_query = kw_res.text.strip().replace('"', '').replace("'", "").replace(" ", "")
            st.info(f"🔎 추출된 검색 키워드: **{search_query}**")

        with st.spinner("2단계: 국가법령정보센터에서 관련 대법원 판례 수집 중..."):
            results = search_prec_list(search_query, display_count=3)
            if not results:
                results = search_prec_list("임대차", display_count=3)
                
            if not results:
                st.error("관련 판례를 찾을 수 없습니다. 질문을 조금 더 구체적으로 작성해 보세요.")
                st.stop()

            context_text = ""
            with st.expander("📚 수집된 실제 판례 목록 (클릭하여 펼치기)", expanded=False):
                for idx, prec in enumerate(results, 1):
                    st.markdown(f"**{idx}. {prec['court_name']} {prec['case_no']}** - *{prec['case_name']}* ({prec['judge_date']} 선고)")
                    context_text += get_prec_detail(prec["prec_id"])

        with st.spinner("3단계: 실제 판례를 바탕으로 정밀 분석 보고서 작성 중..."):
            analysis_prompt = f"""
            당신은 엄격한 법률 AI 어시스턴트입니다.
            아래 제공된 [실제 판례 데이터]만을 근거로 사용자의 질문에 답하세요.
            
            [작성 규칙]
            1. 반드시 제공된 실제 판례 데이터의 내용에만 근거하여 답변하세요. 없는 사실을 절대 지어내지 마세요.
            2. 답변 작성 시 판례의 정확한 사건번호와 법원명을 명시하세요.
            3. 질문자의 상황에 이 법리가 어떻게 적용되는지 알기 쉽게 설명하세요.
            
            [실제 판례 데이터]:
            {context_text}
            
            [사용자 질문]:
            {user_question}
            """
            
            response = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=analysis_prompt,
                config=types.GenerateContentConfig(temperature=0.2)
            )

        st.success("✅ 분석 완료!")
        st.markdown("### 📋 AI 법률 분석 결과")
        st.markdown(response.text)
