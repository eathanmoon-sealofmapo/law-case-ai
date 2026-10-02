import streamlit as st
import requests
import json
from google import genai
from google.genai import types

# ----------------- 페이지 설정 -----------------
st.set_page_config(
    page_title="AI 판례 분석 어시스턴트",
    page_icon="⚖️",
    layout="centered"
)

st.title("⚖️ AI 판례 기반 법률 어시스턴트")
st.caption("국가법령정보센터 실제 대법원 판례를 실시간으로 검색하여 법률 분석을 제공합니다.")

# ----------------- API 키 로드 -----------------
gemini_key = ""
if hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
    gemini_key = st.secrets["GEMINI_API_KEY"]

if not gemini_key:
    gemini_key = st.sidebar.text_input("Gemini API Key를 입력하세요", type="password")

if not gemini_key:
    st.info("💡 사이드바에 Gemini API 키를 입력하거나 Secrets 설정을 완료해 주세요.")
    st.stop()

client = genai.Client(api_key=gemini_key)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# ----------------- 판례 검색 함수 (본문/제목 포괄 검색) -----------------
def search_prec_list(query: str, display_count: int = 3):
    """법제처 오픈API 판례 검색 (본문 및 판결요지 검색 지원)"""
    url = "http://www.law.go.kr/DRF/lawSearch.do"
    
    # 1차: 본문/판결요지 검색 (search=2), 2차: 사건명 검색 (search=1)
    for search_scope in ["2", "1"]:
        params = {
            "OC": "test",
            "target": "prec",
            "type": "JSON",
            "search": search_scope,
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
            if prec_list:
                return prec_list
        except Exception:
            continue
            
    return []

def get_prec_detail(prec_id: str):
    """판례 본문 요지 조회"""
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

# ----------------- 사용자 인터페이스 -----------------
user_question = st.text_area(
    "궁금한 법률 상황을 자유롭게 입력하세요:",
    placeholder="예: 중고차를 샀는데 침수 사실을 숨겼어. 계약 취소하고 손해배상 받을 수 있어? / 횡단보도 파란불에 건너다 우회전 차량에 치였는데 과실비율이 어떻게 돼?",
    height=120
)

if st.button("관련 판례 검색 및 법률 분석", type="primary", use_container_width=True):
    if not user_question.strip():
        st.warning("질문을 입력해 주세요.")
    else:
        # 1. 다각도 법률 키워드 3개 동시 추출
        with st.spinner("1단계: 질문을 분석하여 핵심 법률 키워드를 도출하는 중..."):
            kw_prompt = f"""
            사용자의 법률 질문에서 판례 검색에 적합한 핵심 법률 키워드(띄어쓰기 없는 2~5글자 명사) 3개를 추출하세요.
            가장 정확한 순서대로 쉼표(,)로 구분해서 단어만 출력하세요.
            예: 사기죄,기망행위,매매계약취소
            
            질문: {user_question}
            키워드:
            """
            kw_res = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=kw_prompt
            )
            raw_keywords = kw_res.text.strip().replace('"', '').replace("'", "")
            keywords = [k.strip() for k in raw_keywords.split(",") if k.strip()]
            st.info(f"🔎 검색 키워드 후보: {', '.join(keywords)}")

        # 2. 키워드별 판례 검색 시도
        results = []
        matched_kw = ""
        with st.spinner("2단계: 국가법령정보센터에서 실제 판례 검색 중..."):
            for kw in keywords:
                results = search_prec_list(kw, display_count=3)
                if results:
                    matched_kw = kw
                    break
                    
            if not results:
                st.error("입력하신 상황에 부합하는 판례를 검색하지 못했습니다. 질문에 구체적인 단어(예: 교통사고, 위약금, 이혼, 사기 등)를 포함하여 다시 질문해 주세요.")
                st.stop()
                
            st.success(f"🎯 키워드 **'{matched_kw}'**(으)로 관련 대법원 판례 {len(results)}건을 찾았습니다.")

            context_text = ""
            with st.expander("📚 수집된 실제 판례 원문 목록 (클릭하여 펼치기)", expanded=True):
                for idx, prec in enumerate(results, 1):
                    st.markdown(f"**{idx}. {prec['court_name']} {prec['case_no']}** - *{prec['case_name']}* ({prec['judge_date']} 선고)")
                    context_text += get_prec_detail(prec["prec_id"])

        # 3. 실제 판례 기반 엄격한 분석
        with st.spinner("3단계: 실제 판결문을 바탕으로 법률 분석 보고서 작성 중..."):
            analysis_prompt = f"""
            당신은 엄격한 법률 AI 어시스턴트입니다.
            아래 제공된 [실제 판례 데이터]만을 근거로 사용자의 질문에 답변하세요.
            
            [작성 규칙]
            1. 반드시 제공된 실제 판례 데이터에 근거하여 작성하세요.
            2. 인용한 판례의 사건번호(예: 대법원 2020다...)를 명확히 표시하세요.
            3. 질문자의 상황에 대법원 판례의 법리가 어떻게 해석 및 적용되는지 명쾌하게 결론을 내려주세요.
            
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

        st.markdown("---")
        st.markdown("### 📋 AI 판례 기반 분석 결과")
        st.markdown(response.text)
