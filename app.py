import streamlit as st
import requests
import re
import urllib.parse
from google import genai
from google.genai import types

# ----------------- 페이지 기본 설정 -----------------
st.set_page_config(
    page_title="AI 법률·판례 통합 분석 서비스",
    page_icon="⚖️",
    layout="wide"
)

st.title("⚖️ AI 현행 법률 & 대법원 판례 통합 분석 어시스턴트")
st.caption("질문을 분석하여 국가법령정보센터의 '현행 법령 조항'과 '대법원 판례'를 동시 검색해 명쾌한 법률 솔루션을 제공합니다.")

# ----------------- API 키 인증 -----------------
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

# ----------------- 유틸리티 및 법제처 연동 모듈 -----------------
def clean_html(text: str) -> str:
    if not text:
        return ""
    text = text.replace("<![CDATA[", "").replace("]]>", "")
    text = re.sub(r'<br\s*/?>', '\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()

# 1. 현행 법령(target=law) 검색 함수
def search_law_list(query: str, display_count: int = 2):
    """법제처 API: 관련 법률 명칭 및 일련번호 조회"""
    url = "http://www.law.go.kr/DRF/lawSearch.do"
    params = {
        "OC": "test",
        "target": "law",
        "type": "JSON",
        "query": query,
        "display": display_count
    }
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
        data = resp.json()
        law_items = data.get("LawSearch", {}).get("law", [])
        if isinstance(law_items, dict):
            law_items = [law_items]
            
        law_list = []
        for it in law_items:
            lid = str(it.get("법령일련번호", "")).strip()
            name = it.get("법령명한글", "").strip()
            if lid and name:
                law_list.append({"law_id": lid, "law_name": name})
        return law_list
    except Exception:
        return []

def get_law_detail(law_id: str):
    """법령 조문 본문 발췌 (XML 파싱)"""
    url = f"http://www.law.go.kr/DRF/lawService.do?OC=test&target=law&ID={law_id}&type=XML"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        resp.encoding = 'utf-8'
        text = resp.text
        
        # 법령 본문 중 핵심 조문 태그 발췌
        articles = re.findall(r'<조문단위>(.*?)</조문단위>', text, re.DOTALL)
        content_sample = []
        for art in articles[:4]: # 관련 조문 앞부분 3~4개 발췌
            art_clean = clean_html(art)
            if art_clean:
                content_sample.append(art_clean)
        return "\n\n".join(content_sample)
    except Exception:
        return ""

# 2. 대법원 판례(target=prec) 검색 함수
def search_prec_list(query: str, display_count: int = 3):
    """법제처 API: 관련 대법원 판례 목록 조회"""
    prec_list = []
    for scope in ["1", "2"]:  # 사건명(1) 우선, 부족하면 본문(2)
        url = "http://www.law.go.kr/DRF/lawSearch.do"
        params = {
            "OC": "test",
            "target": "prec",
            "type": "JSON",
            "search": scope,
            "query": query,
            "display": display_count
        }
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
            data = resp.json()
            items = data.get("PrecSearch", {}).get("prec", [])
            if isinstance(items, dict):
                items = [items]
            
            for it in items:
                pid = str(it.get("판례일련번호", "")).strip()
                if pid and not any(p["prec_id"] == pid for p in prec_list):
                    prec_list.append({
                        "prec_id": pid,
                        "case_no": it.get("사건번호", "").strip(),
                        "case_name": it.get("사건명", "").strip(),
                        "court_name": it.get("법원명", "").strip(),
                        "judge_date": it.get("선고일자", "").strip()
                    })
        except Exception:
            continue
        if len(prec_list) >= 2:
            break
    return prec_list

def get_prec_detail(prec_id: str):
    """판례 판시사항 및 판결요지 본문 조회"""
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
            "reason": extract_tag("판결이유")[:1500]
        }
    except Exception:
        return {"holding": "", "summary": "", "reason": ""}

# ----------------- 웹 인터페이스 -----------------
user_question = st.text_area(
    "💬 법률 관련 상황이나 궁금한 점을 자유롭게 입력하세요:",
    placeholder="예시:\n- 전세 계약이 끝났는데 보증금을 못 받은 상태에서 집주인이 바뀌었어. 누구한테 받아야 해?\n- 중고차 딜러가 침수차 사실을 숨기고 팔았어. 환불과 손해배상이 가능할까?\n- 회사에서 프리랜서(3.3%)로 일했는데 퇴직금을 받을 수 있을까?",
    height=120
)

if st.button("⚖️ 법률 조항 및 판례 통합 분석 시작", type="primary", use_container_width=True):
    if not user_question.strip():
        st.warning("질문을 먼저 입력해 주세요.")
    else:
        with st.status("🔍 질문 분석 및 데이터베이스 실시간 조회 중...", expanded=True) as status:
            # 1. 키워드 도출
            st.write("1️⃣ 질문 분석: 핵심 법률명 및 검색 키워드 추출 중...")
            kw_prompt = f"""
            당신은 법률 전문가입니다. 사용자의 질문을 분석하여 다음 2가지를 쉼표(,)로 구분해 출력하세요:
            1. 적용될 만한 대표 법령명 1개 (예: 주택임대차보호법, 민법, 근로기준법, 형법)
            2. 법제처 판례 검색용 사건명 2개 (예: 임차보증금반환, 손해배상(기), 부당이득금, 사기)
            
            출력 형식: 대표법령,판례검색어1,판례검색어2
            질문: {user_question}
            결과:
            """
            kw_res = client.models.generate_content(model="gemini-3.5-flash-lite", contents=kw_prompt)
            tokens = [t.strip() for t in kw_res.text.strip().replace('"', '').split(",") if t.strip()]
            
            target_law_name = tokens[0] if len(tokens) > 0 else "민법"
            prec_keywords = tokens[1:] if len(tokens) > 1 else ["손해배상"]
            st.write(f"👉 타겟 법령: **{target_law_name}** | 판례 키워드: **{', '.join(prec_keywords)}**")

            # 2. 관련 법령 조문 수집
            st.write("2️⃣ 국가법령정보센터에서 관련 현행 법률 조문 수집 중...")
            law_list = search_law_list(target_law_name, display_count=1)
            law_context = ""
            if law_list:
                law_info = law_list[0]
                law_body = get_law_detail(law_info["law_id"])
                law_context = f"[관련 법령: {law_info['law_name']}]\n{law_body}"
                st.write(f"✅ 관련 법률 확인: {law_info['law_name']}")

            # 3. 관련 대법원 판례 수집
            st.write("3️⃣ 국가법령정보센터에서 관련 대법원 핵심 판례 수집 중...")
            all_precs = []
            seen_ids = set()
            for kw in prec_keywords:
                found = search_prec_list(kw, display_count=2)
                for f in found:
                    if f["prec_id"] not in seen_ids:
                        seen_ids.add(f["prec_id"])
                        all_precs.append(f)
                if len(all_precs) >= 2:
                    break

            prec_payload = []
            for p in all_precs[:2]:
                body = get_prec_detail(p["prec_id"])
                prec_payload.append({"meta": p, "content": body})
            
            st.write(f"✅ 관련 대법원 판례 {len(prec_payload)}건 확보 완료")
            status.update(label="법률 조문 및 판례 데이터 수집 완료!", state="complete", expanded=False)

        # 4. 통합 분석 보고서 작성
        with st.spinner("⚖️ 법률 조항과 대법원 판례를 결합한 통합 분석 보고서를 작성 중입니다..."):
            prec_text = ""
            for idx, item in enumerate(prec_payload, 1):
                m = item["meta"]
                c = item["content"]
                prec_text += f"""
[판례 #{idx}]
- 사건번호: {m['court_name']} {m['case_no']} ({m['case_name']}, {m['judge_date']} 선고)
- 판시사항: {c['holding']}
- 판결요지: {c['summary']}
--------------------------------------------------
"""

            combined_prompt = f"""
            당신은 법률 전문 수석 AI 변호사입니다.
            제공된 [현행 법령 조항]과 [실제 대법원 판례 데이터]를 철저히 근거로 삼아 사용자 질문에 대해 종합 보고서를 작성하세요. 없는 사실을 지어내지 마세요.
            
            [출력 양식]
            ## 1. 📖 관련 법령 조항 및 기본 원칙
            - 적용되는 법률명과 해당 법률이 규정하는 핵심 기준을 알기 쉽게 설명
            
            ## 2. 🏛️ 대법원 핵심 판례 요약
            (수집된 판례별로 작성)
            ### 🔹 [사건번호] ([선고일자] 선고) - [사건명]
            - **핵심 쟁점**: 다투어진 핵심 법률 문제
            - **대법원 판단 요약**: 법원의 최종 판단 취지 (2~3줄 요약)
            
            ## 3. ⚖️ 질문자에 대한 종합 검토 및 실무 솔루션
            - **상황 분석**: 위 법령과 판례 법리를 적용했을 때 질문자의 유불리 판단
            - **실제 취해야 할 구체적 조치**: 질문자가 지금 당장 준비해야 할 증거나 행동 요령 (예: 내용증명, 지급명령, 소송 등)
            
            [현행 법령 데이터]:
            {law_context if law_context else '관련 법령 정보 없음'}
            
            [실제 대법원 판례 데이터]:
            {prec_text}
            
            [사용자 질문]:
            {user_question}
            """
            
            res = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=combined_prompt,
                config=types.GenerateContentConfig(temperature=0.2)
            )

        st.markdown(res.text)

        # 하단 원문 열람 아코디언
        with st.expander("🔎 수집된 실제 법률 및 판례 원문 확인"):
            if law_context:
                st.markdown("#### 📜 법률 조문 발췌")
                st.text(law_context)
                st.divider()
            for item in prec_payload:
                m = item["meta"]
                c = item["content"]
                st.markdown(f"#### 🏛️ {m['court_name']} {m['case_no']} ({m['case_name']})")
                st.markdown(f"**【판시사항】**\n\n{c['holding']}")
                st.markdown(f"**【판결요지】**\n\n{c['summary']}")
                st.divider()
