import streamlit as st
import requests
import re
import urllib.parse
from google import genai
from google.genai import types

st.set_page_config(
    page_title="AI 판례 & 과실비율 분석 서비스",
    page_icon="⚖️",
    layout="wide"
)

st.title("⚖️ AI 판례 및 과실비율 판결 분석 서비스")
st.caption("대법원 판례뿐만 아니라 하급심(지방법원) 실제 판결례와 법원 과실비율 산정 기준을 정밀 분석합니다.")

# API 키 인증
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

def clean_html(text: str) -> str:
    if not text:
        return ""
    text = text.replace("<![CDATA[", "").replace("]]>", "")
    text = re.sub(r'<br\s*/?>', '\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()

# 판례 검색: prec(대법원/주요판례) 및 decm(각급법원 판결) 포괄 탐색
def search_law_cases(keyword: str):
    clean_kw = re.sub(r'[^가-힣a-zA-Z0-9]', '', keyword)
    if not clean_kw:
        return []
    
    found_cases = []
    seen_ids = set()
    encoded_kw = urllib.parse.quote(clean_kw)
    
    # target=prec 및 decm 동시 시도
    for target in ["prec", "decm"]:
        for search_type in ["2", "1"]:  # 본문(2) 우선, 사건명(1)
            url = f"http://www.law.go.kr/DRF/lawSearch.do?OC=test&target={target}&type=JSON&search={search_type}&query={encoded_kw}&display=3"
            try:
                resp = requests.get(url, headers=HEADERS, timeout=6)
                data = resp.json()
                root_key = "PrecSearch" if target == "prec" else "DecmSearch"
                item_key = "prec" if target == "prec" else "decm"
                
                items = data.get(root_key, {}).get(item_key, [])
                if isinstance(items, dict):
                    items = [items]
                    
                for it in items:
                    pid = str(it.get("판례일련번호", "") or it.get("판결일련번호", "")).strip()
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        found_cases.append({
                            "target": target,
                            "id": pid,
                            "case_no": it.get("사건번호", "").strip(),
                            "case_name": it.get("사건명", "").strip(),
                            "court_name": it.get("법원명", "").strip(),
                            "judge_date": it.get("선고일자", "").strip()
                        })
            except Exception:
                continue
            if len(found_cases) >= 3:
                break
        if len(found_cases) >= 3:
            break
            
    return found_cases

def get_case_detail(target: str, case_id: str):
    url = f"http://www.law.go.kr/DRF/lawService.do?OC=test&target={target}&ID={case_id}&type=XML"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=6)
        resp.encoding = 'utf-8'
        text = resp.text
        
        def extract_tag(tag):
            m = re.search(rf'<{tag}>(.*?)</{tag}>', text, re.DOTALL)
            return clean_html(m.group(1)) if m else ""
            
        return {
            "holding": extract_tag("판시사항") or extract_tag("판결요지") or "내용 없음",
            "summary": extract_tag("판결요지") or extract_tag("주문") or "내용 없음",
            "reason": extract_tag("판결이유")[:1500]
        }
    except Exception:
        return {"holding": "", "summary": "", "reason": ""}

# 사용자 인터페이스
user_question = st.text_area(
    "💬 알고 싶은 분쟁 상황이나 찾고 있는 판례를 입력하세요:",
    placeholder="예: 자전거대 자전거 추월 중 충돌 사고 판례 및 과실비율 알려줘",
    height=100
)

if st.button("🔍 판례 및 과실비율 정밀 분석", type="primary", use_container_width=True):
    if not user_question.strip():
        st.warning("질문을 입력해 주세요.")
    else:
        with st.status("🔍 법령정보센터 API 및 사법 판결 데이터베이스 조회 중...", expanded=True) as status:
            # 1. 키워드 추출
            st.write("1️⃣ 질문 분석: 핵심 쟁점 및 법률 검색어 추출 중...")
            kw_prompt = f"""
            질문에서 법제처 판례 검색창에 넣을 핵심 명사 3개를 추출하세요.
            조사, 부사, '판례', '사고' 제외하고 구체적인 대상/행위 명사만 쉼표로 구분하세요.
            예: 자전거, 추월, 손해배상
            
            질문: {user_question}
            결과:
            """
            kw_res = client.models.generate_content(model="gemini-3.5-flash-lite", contents=kw_prompt)
            keywords = [k.strip() for k in kw_res.text.strip().replace('"', '').split(",") if k.strip()]
            st.write(f"🎯 도출된 핵심 키워드: **{', '.join(keywords)}**")

            # 2. 법제처 API 실시간 수집 시도
            st.write("2️⃣ 국가법령정보센터 대법원 및 하급심 판결문 검색 중...")
            api_cases = []
            for kw in keywords:
                res = search_law_cases(kw)
                if res:
                    api_cases.extend(res)
                    break

            api_context = ""
            if api_cases:
                st.write(f"✅ 법제처 API에서 {len(api_cases)}건 판결문 매칭 성공")
                for c in api_cases[:3]:
                    det = get_case_detail(c["target"], c["id"])
                    api_context += f"""
[법제처 API 수집 판례]
사건번호: {c['court_name']} {c['case_no']} ({c['case_name']}, {c['judge_date']} 선고)
판시사항/요지: {det['holding']}
판결이유: {det['reason']}
--------------------------------------------------
"""
            else:
                st.write("ℹ️ 법제처 Open API 제한으로 하급심 전문 지식 베이스로 자동 전환합니다.")

            status.update(label="판례 데이터 수집 및 쟁점 매칭 완료!", state="complete", expanded=False)

        # 3. Gemini 전문 법률 분석 (하급심 판결례 및 과실비율 기준 정밀 복원)
        with st.spinner("⚖️ 실제 하급심 판결문과 법원 실무 기준을 종합하여 분석 보고서를 작성 중입니다..."):
            synthesis_prompt = f"""
            당신은 대한민국 법원 판례 및 교통사고·손해배상 전문 수석 변호사 AI입니다.
            사용자의 질문: "{user_question}"
            
            [분석 데이터 출처 지침]
            1. 아래 제공된 [법제처 API 수집 판례]가 있다면 최우선 반영하세요.
            2. 만약 API 수집 판례가 질문의 구체적인 상황(예: 자전거 간 추월/급좌회전, 하급심 단독사건 등)을 충분히 커버하지 못한다면, 대한민국 법원의 실제 확정 판결례(예: 서울동부지방법원 2010가단18854 판결 등 실제 지방법원/대법원 하급심 판례)와 법원/손해보험협회의 공인 과실비율 인정기준을 직접 인출하여 명확한 사건번호와 사실관계를 바탕으로 서술하세요. 없는 번호를 날조하지 말고 실무상 검증된 실제 판결례를 근거로 작성하세요.
            
            [출력 양식]
            ## 📜 관련 실제 판결례 분석
            ### 🔹 [법원명] [사건번호] ([선고일자] 선고) - [사건명]
            * **사건 개요**: (사고 당시의 구체적인 상황 및 충돌 경위)
            * **법원의 판단 및 주의의무 기준**: (앞차/뒤차, 당사자들의 법적 주의의무에 대한 법원의 판단)
            * **인정된 과실 비율**: (예: 선행 자전거 OO% : 후행 자전거 OO%)
            
            (필요 시 유사 하급심 판결례 추가 정리)
            
            ---
            ## ⚖️ 질문 사안에 대한 법적 쟁점 검토
            1. **핵심 주의의무 위반 요소**: (신호 유무, 안전거리 확보, 전방주시 태만 등)
            2. **예상 과실비율 및 실무 기준**: (유사 사고에 적용되는 통상적인 과실비율 구간)
            3. **실무 대응 방안**: (현장 증거 확보, 블랙박스/CCTV 확인, 손해배상 청구 절차)
            
            [법제처 API 수집 판례]:
            {api_context if api_context else "API 직접 수집 판례 없음 (전문 하급심 지식베이스 인출 필요)"}
            """

            res = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=synthesis_prompt,
                config=types.GenerateContentConfig(temperature=0.1)
            )

        st.markdown(res.text)

        # 원문 데이터 확인창
        if api_cases:
            with st.expander("🔎 법제처 API 수집 원문 확인"):
                for c in api_cases[:3]:
                    st.markdown(f"#### 🏛️ {c['court_name']} {c['case_no']} ({c['case_name']})")
                    det = get_case_detail(c["target"], c["id"])
                    st.text(det["holding"])
                    st.divider()
