from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from math import floor
import re
from uuid import uuid4

import streamlit as st


# 精簡模組：只留下討論時間與合作規範
MODULES = ["討論時間安排", "合作規範系統"]
TIME_OPTIONS = [1, 2, 3, 6, 12, 24, 48]


st.set_page_config(
    page_title="小組協作平台",
    page_icon="✅",
    layout="wide",
)


# 利用 cache_resource 建立全域、跨瀏覽器共用的記憶體資料庫
@st.cache_resource
def get_global_db():
    return defaultdict(lambda: {
        "members": [],
        "availability": {},
        "selected_modules": ["討論時間安排", "合作規範系統"],
        "norm_candidates": [],
    })


def ensure_state() -> None:
    query_params = st.query_params
    default_room = query_params.get("room", "預設房間")

    if "current_room" not in st.session_state:
        st.session_state.current_room = default_room

    # 取得全域共用資料庫
    global_db = get_global_db()
    room = st.session_state.current_room

    # 將當前房間的資料指標綁定到捷徑變數
    st.session_state.members = global_db[room]["members"]
    st.session_state.availability = global_db[room]["availability"]
    st.session_state.selected_modules = global_db[room]["selected_modules"]
    st.session_state.norm_candidates = global_db[room]["norm_candidates"]


def member_label(member: dict) -> str:
    display_name = member["nickname"] or member["name"]
    return f'👤 {display_name}'


def active_member_ids() -> list[str]:
    return [member["id"] for member in st.session_state.members]


def majority_count() -> int:
    member_count = len(st.session_state.members)
    return floor(member_count / 2) + 1 if member_count else 1


def half_hour_slots(start_hour: int = 8, end_hour: int = 22) -> list[str]:
    slots = []
    current = datetime.combine(date.today(), time(start_hour))
    end = datetime.combine(date.today(), time(end_hour))
    while current < end:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=30)
    return slots


def parse_reply_hours(text: str) -> int | None:
    match = re.search(r"(\d{1,2})\s*(小時|hr|hour|h)", text, flags=re.IGNORECASE)
    if not match:
        return None
    value = int(match.group(1))
    if value < 0 or value > 72:
        return None
    return value


def classify_norm(raw_text: str) -> dict:
    text = raw_text.strip()
    lowered = text.lower()
    reply_hours = parse_reply_hours(text)

    if len(text) < 4:
        return {
            "status": "rejected",
            "reason": "內容過短，無法形成可討論條文。",
            "category": "格式問題",
            "standard": text,
            "parameter": None,
        }

    blocked_terms = ["笨", "白癡", "垃圾", "滾", "死", "爛人"]
    if any(term in text for term in blocked_terms):
        return {
            "status": "rejected",
            "reason": "內容包含攻擊性語句，未推送至背書區。",
            "category": "不合格內容",
            "standard": text,
            "parameter": None,
        }

    if reply_hours is not None or any(keyword in text for keyword in ["回覆", "訊息", "已讀"]):
        hours = reply_hours or 24
        return {
            "status": "backing",
            "reason": "",
            "category": "訊息回覆時效",
            "standard": f"小組訊息應於 {hours} 小時內回覆；若暫時無法處理，需先簡短告知。",
            "parameter": hours,
        }

    if any(keyword in text for keyword in ["開會", "會議", "準時", "遲到"]):
        return {
            "status": "backing",
            "reason": "",
            "category": "會議準則",
            "standard": "小組會議應準時出席；若需請假或延後，應提前通知全組。",
            "parameter": None,
        }

    if any(keyword in text for keyword in ["分工", "負責", "期限", "作業"]):
        return {
            "status": "backing",
            "reason": "",
            "category": "分工與交付",
            "standard": "每位成員需確認自己的任務與截止時間，並在期限前回報進度。",
            "parameter": None,
        }

    if any(keyword in lowered for keyword in ["respect", "尊重", "禮貌", "語氣"]):
        return {
            "status": "backing",
            "reason": "",
            "category": "溝通態度",
            "standard": "討論時應保持尊重與具體回饋，避免人身攻擊或情緒化指責。",
            "parameter": None,
        }

    return {
        "status": "backing",
        "reason": "",
        "category": "其他合作期待",
        "standard": text,
        "parameter": None,
    }


def find_existing_candidate(category: str, standard: str) -> dict | None:
    for candidate in st.session_state.norm_candidates:
        if category == "訊息回覆時效" and candidate["category"] == category:
            return candidate
        if candidate["standard"] == standard:
            return candidate
    return None


def add_norm_candidate(raw_text: str) -> tuple[bool, str]:
    result = classify_norm(raw_text)
    if result["status"] == "rejected":
        return False, result["reason"]

    existing = find_existing_candidate(result["category"], result["standard"])
    if existing:
        if result["parameter"] is not None:
            existing["options"].add(result["parameter"])
        existing["sources"].append(raw_text.strip())
        return True, "已整併到既有條文，並更新參數選項。"

    option = result["parameter"]
    st.session_state.norm_candidates.append(
        {
            "id": uuid4().hex,
            "category": result["category"],
            "standard": result["standard"],
            "options": {option} if option is not None else set(),
            "supporters": set(),
            "opponents": set(),
            "preferences": {},
            "sources": [raw_text.strip()],
        }
    )
    return True, "已送入背書區。"


def candidate_status(candidate: dict) -> tuple[str, int, int, int | None]:
    member_count = len(st.session_state.members)
    support_count = len(candidate["supporters"])
    opponent_count = len(candidate["opponents"])
    preferred_option = None
    if candidate["preferences"]:
        option_counts = defaultdict(int)
        for option in candidate["preferences"].values():
            option_counts[option] += 1
        preferred_option = sorted(option_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]

    if member_count == 0:
        return "待背書", support_count, opponent_count, preferred_option
    if support_count >= majority_count():
        return "Active", support_count, opponent_count, preferred_option
    if support_count + opponent_count == member_count and support_count < majority_count():
        return "待議", support_count, opponent_count, preferred_option
    return "背書中", support_count, opponent_count, preferred_option


def render_header() -> None:
    st.title("🤝 小組協作平台")
    st.caption("建立獨立討論房間、設定成員名單，即可進行時間協調與合作公約匿名徵集背書。")


def render_room_setup() -> None:
    st.subheader("🚪 房間系統設定")
    with st.container(border=True):
        st.write(f"🏠 目前所在房間：**{st.session_state.current_room}**")
        
        next_room = st.text_input("輸入房間名稱以切換或創建：", placeholder="例如：企劃一組、期末專題")
        
        c1, c2, c3 = st.columns([1.5, 1.5, 1])
        if c1.button("進入 / 建立房間", use_container_width=True, type="primary"):
            if next_room.strip():
                st.session_state.current_room = next_room.strip()
                st.query_params["room"] = next_room.strip()
                st.success(f"已成功切換至房間：{next_room.strip()}")
                st.rerun()
            else:
                st.error("房間名稱不能為空！")
                
        if c2.button("📋 複製此房間連結", use_container_width=True):
            st.info("請直接複製瀏覽器上方網址列連結給組員，即可一同進入此房間！")
            
        if c3.button("🔄 刷新資料", use_container_width=True):
            st.rerun()


def render_member_setup() -> None:
    st.subheader("1. 成員名單設定")
    with st.form("member_form", clear_on_submit=True):
        cols = st.columns([2, 2, 1])
        name = cols[0].text_input("姓名", placeholder="例如：王小明")
        nickname = cols[1].text_input("暱稱", placeholder="可留空")
        submitted = cols[2].form_submit_button("加入小組", use_container_width=True)

    if submitted:
        if not name.strip() and not nickname.strip():
            st.warning("請至少填寫姓名或暱稱。")
        else:
            st.session_state.members.append(
                {
                    "id": uuid4().hex,
                    "name": name.strip() or nickname.strip(),
                    "nickname": nickname.strip(),
                }
            )
            st.success("成員已加入。")
            st.rerun()

    st.metric("目前房間總人數", len(st.session_state.members))
    if st.session_state.members:
        for member in st.session_state.members:
            cols = st.columns([5, 1])
            cols[0].write(member_label(member))
            if cols[1].button("移除", key=f"remove_{member['id']}", use_container_width=True):
                st.session_state.members.remove(member)
                st.session_state.availability.pop(member["id"], None)
                st.rerun()
    else:
        st.info("當前房間尚未有成員加入。")


def render_module_picker() -> None:
    st.subheader("2. 啟用功能模組")
    new_modules = st.multiselect(
        "若需要調整，可由成員自由增減啟用的模組項目。",
        MODULES,
        default=st.session_state.selected_modules,
    )
    if new_modules != st.session_state.selected_modules:
        global_db = get_global_db()
        global_db[st.session_state.current_room]["selected_modules"] = new_modules
        st.rerun()


def render_schedule_module() -> None:
    st.subheader("🗓️ 討論時間安排")
    if not st.session_state.members:
        st.info("請先加入至少一位成員。")
        return

    cols = st.columns([1, 1, 2])
    start_day = cols[0].date_input("起始日期", value=date.today())
    day_count = cols[1].number_input("天數", min_value=1, max_value=14, value=5, step=1)
    mode = cols[2].segmented_control(
        "討論形式",
        options=["實體討論", "線上討論", "皆可"],
        default="皆可",
    )

    days = [start_day + timedelta(days=offset) for offset in range(day_count)]
    slots = half_hour_slots()
    
    member_options = {member_label(member): member["id"] for member in st.session_state.members}
    selected_label = st.selectbox("🎯 請選擇目前正在填寫的成員", list(member_options.keys()))
    selected_member_id = member_options[selected_label]

    temp_key = f"temp_slots_{selected_member_id}"
    if temp_key not in st.session_state:
        st.session_state[temp_key] = set(st.session_state.availability.get(selected_member_id, set()))

    st.markdown(f"#### ✍️ 請勾選 **{selected_label}** 可以配合的時段")
    
    st.write("💡 **快捷填寫按鈕：**")
    c1, c2, c3 = st.columns(3)
    if c1.button("📅 平日晚上全部勾選 (18:00後)", key=f"quick_p_{selected_member_id}", use_container_width=True):
        for d in days:
            if d.weekday() < 5:
                for s in slots:
                    if s >= "18:00":
                        st.session_state[temp_key].add(f"{d.isoformat()} {s}")
        st.rerun()
        
    if c2.button("🏖️ 假日整天全部勾選", key=f"quick_h_{selected_member_id}", use_container_width=True):
        for d in days:
            if d.weekday() >= 5:
                for s in slots:
                    st.session_state[temp_key].add(f"{d.isoformat()} {s}")
        st.rerun()
        
    if c3.button("❌ 清除該成員所有勾選", key=f"quick_c_{selected_member_id}", use_container_width=True):
        st.session_state[temp_key].clear()
        st.rerun()

    day_tabs = st.tabs([d.strftime("%m/%d (%a)") for d in days])
    for i, d in enumerate(days):
        with day_tabs[i]:
            st.caption("☀️ 早上 (08:00 - 12:00)")
            cols_morning = st.columns(4)
            
            st.caption("⛅ 下午 (12:00 - 18:00)")
            cols_afternoon = st.columns(4)
            
            st.caption("🌙 晚上 (18:00 - 22:00)")
            cols_evening = st.columns(4)
            
            m_idx, a_idx, e_idx = 0, 0, 0
            for s in slots:
                slot_key = f"{d.isoformat()} {s}"
                is_checked = slot_key in st.session_state[temp_key]
                
                if s < "12:00":
                    col = cols_morning[m_idx % 4]
                    m_idx += 1
                elif s < "18:00":
                    col = cols_afternoon[a_idx % 4]
                    a_idx += 1
