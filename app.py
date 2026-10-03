import streamlit as st
import requests
import re
import urllib.parse
from google import genai
from google.genai import types

# ----------------- 페이지 기본 설정 -----------------
st.set_page_config(
    page_title="AI 대법원 판례 검색 & 요약 서비스",
    page_icon="⚖️",
    layout="wide"
)

st.title("⚖️ 질문 맞춤형 AI 대법원 판례 검색 & 요약")
st.caption("질문을 분석하여 가장 밀접한 국가법령정보센터 대법원 판례를 찾고 핵심 요약을 제공합니다.")

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

# ----------------- 법제처 API 연동 모듈 -----------------
def clean_html(text: str) -> str:
    if not text:
        return ""
    text = text.replace("<![CDATA[", "").replace("]]>", "")
    text = re.sub(r'<br\s*/?>', '\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()

def search_prec_by_keyword(query: str, display_count: int = 5):
    """법제처 API: 사건명 및 본문에서 유의미한 판례 목록 추출"""
    prec_list = []
    
    # 1. 사건명 위주(search=1) 우선 검색 후, 부족하면 본문(search=2) 검색
    for scope in ["1", "2"]:
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
                case_no = it.get("사건번호", "").strip()
                if pid and not any(p["prec_id"] == pid for p in prec_list):
                    prec_list.append({
                        "prec_id": pid,
                        "case_no": case_no,
                        "case_name": it.get("사건명", "").strip(),
                        "court_name": it.get("법원명", "").strip(),
                        "judge_date": it.get("선고일자", "").strip()
                    })
        except Exception:
            continue
            
        if len(prec_list) >= 3:
            break
            
    return prec_list

def get_prec_full_content(prec_id: str):
    """판례의 판시사항, 판결요지, 판결이유를 확실하게 추출 (XML 파싱 백업 적용)"""
    url = f"http://www.law.go.kr/DRF/lawService.do?OC=test&target=prec&ID={prec_id}&type=XML"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        resp.encoding = 'utf-8'
        text = resp.text
        
        def extract_tag(tag):
            m = re.search(rf'<{tag}>(.*?)</{tag}>', text, re.DOTALL)
            return clean_html(m.group(1)) if m else ""
            
        holding = extract_tag("판시사항")
        summary = extract_tag("판결요지")
        reason = extract_tag("판결이유")
        
        return {
            "holding": holding if holding else "판시사항 정보 없음",
            "summary": summary if summary else "판결요지 정보 없음",
            "reason": reason[:2000] if reason else ""
        }
    except Exception:
        return {"holding": "", "summary": "", "reason": ""}

# ----------------- 사용자 인터페이스 -----------------
user_question = st.text_area(
    "💬 법률 관련 상황이나 알고 싶은 내용을 구체적으로 입력하세요:",
    placeholder="예시:\n- 중고차를 샀는데 침수차량인 사실을 숨겼어. 계약 취소하고 손해배상 받을 수 있어?\n- 퇴직금을 안 주려고 직원을 프리랜서 3.3% 사업소득자로 등록해뒀는데 퇴직금 청구 가능한가?\n- 아파트 윗집 누수로 천장이 젖었는데 수리비와 위자료를 어떻게 청구해?",
    height=120
)

col1, col2 = st.columns([1, 4])
with col1:
    search_button = st.button("🔍 연관 판례 검색 및 요약", type="primary", use_container_width=True)

if search_button:
    if not user_question.strip():
        st.warning("질문을 먼저 입력해 주세요.")
    else:
        # 1단계: 법제처 맞춤형 실제 사건명 및 법률 용어 도출
        with st.status("🔍 질문 분석 및 최적의 판례 검색어 추출 중...", expanded=True) as status:
            prompt_keyword = f"""
            당신은 법률 검색 전문가입니다.
            사용자의 일상 질문을 분석하여, 대한민국 법원/법제처 판례 데이터베이스에서 가장 정확한 판례를 찾을 수 있는 검색어를 3개 추천하세요.
            
            [규칙]
            1. 실제 법원 사건명(예: 손해배상(기), 부당이득금, 소유권이전등기, 사기, 임차보증금반환)이나 대표 법률개념 단어여야 합니다.
            2. 쉼표(,)로만 구분해서 3개의 단어만 출력하세요. (공백 금지)
            
            사용자 질문: {user_question}
            검색어:
            """
            kw_res = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=prompt_keyword
            )
            raw_kws = kw_res.text.strip().replace('"', '').replace("'", "").replace(" ", "")
            keywords = [k.strip() for k in raw_kws.split(",") if k.strip()]
            
            st.write(f"추출된 법률 검색어: **{', '.join(keywords)}**")
            
            # 2단계: 판례 수집
            st.write("🏛️ 국가법령정보센터에서 관련 대법원 판례 수집 중...")
            all_precs = []
            seen_ids = set()
            
            for kw in keywords:
                found = search_prec_by_keyword(kw, display_count=3)
                for f in found:
                    if f["prec_id"] not in seen_ids:
                        seen_ids.add(f["prec_id"])
                        all_precs.append(f)
                if len(all_precs) >= 3:
                    break
                    
            if not all_precs:
                status.update(label="판례 검색 실패", state="error")
                st.error("관련 판례를 찾지 못했습니다. 상황 설명을 조금 더 자세하게(예: 사건의 경위, 손해 내용 등) 적어주세요.")
                st.stop()

            # 판례 본문 데이터 병합
            st.write(f"📥 수집된 {len(all_precs)}건 판례의 판결요지 본문 추출 중...")
            prec_payload = []
            for p in all_precs[:3]:  # 핵심 판례 최대 3건 정밀 요약
                body = get_prec_full_content(p["prec_id"])
                prec_payload.append({
                    "meta": p,
                    "content": body
                })
            
            status.update(label="판례 분석 및 핵심 요약 완료!", state="complete", expanded=False)

        # 3단계: Gemini를 통한 개별 판례 구조화 요약 및 질의 적용
        with st.spinner("⚖️ 판례별 핵심 요약과 법률 검토 결과를 작성 중입니다..."):
            context_blocks = ""
            for idx, item in enumerate(prec_payload, 1):
                m = item["meta"]
                c = item["content"]
                context_blocks += f"""
[판례 #{idx}]
- 사건번호: {m['court_name']} {m['case_no']} ({m['case_name']})
- 선고일자: {m['judge_date']}
- 판시사항: {c['holding']}
- 판결요지: {c['summary']}
- 판결이유 일부: {c['reason']}
--------------------------------------------------
"""

            summary_prompt = f"""
            당신은 판례 분석 전문 수석 변호사 AI입니다.
            제공된 [실제 대법원 판례 데이터]를 철저히 검토하여, 사용자 질문과 연관된 판례를 읽기 쉽게 요약하고 명확한 법률적 결론을 내려주세요.
            
            [반드시 지켜야 할 작성 양식]
            
            ## 📜 연관 대법원 핵심 판례 요약
            제공된 각 판례에 대해 아래 항목을 누락 없이 순서대로 요약하세요:
            
            ### 🔹 [사건번호] ([법원명], [선고일자] 선고) - [사건명]
            * **핵심 쟁점**: 이 판결에서 법적으로 가장 크게 다투어진 문제 (1~2줄)
            * **대법원 판단 요약**: 법원이 내린 최종 기준과 판결 취지를 알기 쉬운 문장으로 정리 (2~3줄)
            * **사건과의 연관성**: 질문자의 상황과 이 판례가 어떻게 맞닿아 있는지 설명 (1~2줄)
            
            (판례가 여러 개면 위 3개 블록을 번호별로 반복)
            
            ---
            
            ## 💡 질문 상황에 대한 법률 적용 및 결론
            1. **판례에 따른 법적 유불리**: 질문자의 입장에서 판례 법리를 적용했을 때 유리한 점과 주의할 점
            2. **실제 취할 수 있는 구체적 조치**: 질문자가 지금 바로 취해야 할 실질적인 해결 방안 (예: 증거 확보, 내용증명, 청구 방법 등)
            
            [실제 대법원 판례 데이터]:
            {context_blocks}
            
            [사용자 질문]:
            {user_question}
            """
            
            res = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=summary_prompt,
                config=types.GenerateContentConfig(temperature=0.2)
            )

        # 결과 화면 출력
        st.markdown(res.text)

        # 국가법령정보센터 원문 보기 아코디언
        with st.expander("🔎 판례 원문(판시사항·판결요지) 전문 확인하기"):
            for item in prec_payload:
                m = item["meta"]
                c = item["content"]
                st.subheader(f"{m['court_name']} {m['case_no']} - {m['case_name']}")
                st.markdown(f"**선고일자:** {m['judge_date']}")
                st.markdown(f"**【판시사항】**\n\n{c['holding']}")
                st.markdown(f"**【판결요지】**\n\n{c['summary']}")
                st.divider()
