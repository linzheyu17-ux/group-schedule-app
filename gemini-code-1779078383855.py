from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from math import floor
import re
from uuid import uuid4

import streamlit as st

# 只保留時間安排與合作規範
MODULES = ["討論時間安排", "合作規範系統"]
TIME_OPTIONS = [1, 2, 3, 6, 12, 24, 48]

st.set_page_config(
    page_title="小組協作平台",
    page_icon="✅",
    layout="wide",
)

# ==========================================
# 全域資料庫 (使用 Cache 達成跨使用者的連線資料共享)
# ==========================================
@st.cache_resource
def get_database() -> dict:
    return {}

DB = get_database()

def ensure_state() -> None:
    if "user_id" not in st.session_state:
        st.session_state.user_id = uuid4().hex
    if "room_name" not in st.session_state:
        st.session_state.room_name = None
    if "user_name" not in st.session_state:
        st.session_state.user_name = ""

# ==========================================
# 核心邏輯與輔助函式
# ==========================================
def majority_count(room: dict) -> int:
    member_count = len(room["members"])
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
    return value if 0 <= value <= 72 else None

def classify_norm(raw_text: str) -> dict:
    text = raw_text.strip()
    lowered = text.lower()
    reply_hours = parse_reply_hours(text)

    if len(text) < 4:
        return {"status": "rejected", "reason": "內容過短，無法形成可討論條文。", "category": "格式問題", "standard": text, "parameter": None}

    blocked_terms = ["笨", "白癡", "垃圾", "滾", "死", "爛人"]
    if any(term in text for term in blocked_terms):
        return {"status": "rejected", "reason": "內容包含攻擊性語句，未推送至背書區。", "category": "不合格內容", "standard": text, "parameter": None}

    if reply_hours is not None or any(keyword in text for keyword in ["回覆", "訊息", "已讀"]):
        hours = reply_hours or 24
        return {"status": "backing", "reason": "", "category": "訊息回覆時效", "standard": f"小組訊息應於 {hours} 小時內回覆；若暫時無法處理，需先簡短告知。", "parameter": hours}

    if any(keyword in text for keyword in ["開會", "會議", "準時", "遲到"]):
        return {"status": "backing", "reason": "", "category": "會議準則", "standard": "小組會議應準時出席；若需請假或延後，應提前通知全組。", "parameter": None}

    if any(keyword in text for keyword in ["分工", "負責", "期限", "作業"]):
        return {"status": "backing", "reason": "", "category": "分工與交付", "standard": "每位成員需確認自己的任務與截止時間，並在期限前回報進度。", "parameter": None}

    if any(keyword in lowered for keyword in ["respect", "尊重", "禮貌", "語氣"]):
        return {"status": "backing", "reason": "", "category": "溝通態度", "standard": "討論時應保持尊重與具體回饋，避免人身攻擊或情緒化指責。", "parameter": None}

    return {"status": "backing", "reason": "", "category": "其他合作期待", "standard": text, "parameter": None}

def find_existing_candidate(room: dict, category: str, standard: str) -> dict | None:
    for candidate in room["norm_candidates"]:
        if category == "訊息回覆時效" and candidate["category"] == category:
            return candidate
        if candidate["standard"] == standard:
            return candidate
    return None

def add_norm_candidate(room: dict, raw_text: str) -> tuple[bool, str]:
    result = classify_norm(raw_text)
    if result["status"] == "rejected":
        return False, result["reason"]

    existing = find_existing_candidate(room, result["category"], result["standard"])
    if existing:
        if result["parameter"] is not None:
            existing["options"].add(result["parameter"])
        existing["sources"].append(raw_text.strip())
        return True, "已整併到既有條文，並更新參數選項。"

    option = result["parameter"]
    room["norm_candidates"].append({
        "id": uuid4().hex,
        "category": result["category"],
        "standard": result["standard"],
        "options": {option} if option is not None else set(),
        "supporters": set(),
        "opponents": set(),
        "preferences": {},
        "sources": [raw_text.strip()],
    })
    return True, "已送入背書區。"

def candidate_status(room: dict, candidate: dict) -> tuple[str, int, int, int | None]:
    member_count = len(room["members"])
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
    if support_count >= majority_count(room):
        return "Active", support_count, opponent_count, preferred_option
    if support_count + opponent_count == member_count and support_count < majority_count(room):
        return "待議", support_count, opponent_count, preferred_option
    return "背書中", support_count, opponent_count, preferred_option

# ==========================================
# 頁面與模組渲染
# ==========================================
def render_auth() -> None:
    st.title("🤝 小組協作平台 - 房間大廳")
    st.write("請建立或加入一個小組房間，所有組員需輸入相同的密碼以確保資料統整在同一處。")
    
    tab1, tab2 = st.tabs(["🔑 加入既有房間", "🏠 建立新房間 (成為主持人)"])
    
    with tab1:
        with st.form("join_form"):
            r_name = st.text_input("房間名稱")
            r_pass = st.text_input("房間密碼", type="password")
            u_name = st.text_input("你的名字/暱稱")
            submitted = st.form_submit_button("加入房間", use_container_width=True)
            
            if submitted:
                if not r_name or not r_pass or not u_name:
                    st.warning("請填寫所有欄位。")
                elif r_name not in DB:
                    st.error("找不到此房間，請確認名稱是否正確。")
                elif DB[r_name]["password"] != r_pass:
                    st.error("密碼錯誤，請重新輸入。")
                else:
                    st.session_state.room_name = r_name
                    st.session_state.user_name = u_name
                    if st.session_state.user_id not in DB[r_name]["members"]:
                        DB[r_name]["members"][st.session_state.user_id] = {"name": u_name, "ready": False}
                    st.rerun()

    with tab2:
        with st.form("create_form"):
            r_name = st.text_input("設定房間名稱 (請使用獨特的名稱)")
            r_pass = st.text_input("設定房間密碼", type="password")
            u_name = st.text_input("你的名字/暱稱")
            submitted = st.form_submit_button("建立並進入", use_container_width=True)
            
            if submitted:
                if not r_name or not r_pass or not u_name:
                    st.warning("請填寫所有欄位。")
                elif r_name in DB:
                    st.error("此房間名稱已被使用，請換一個。")
                else:
                    DB[r_name] = {
                        "password": r_pass,
                        "host_id": st.session_state.user_id,
                        "step": 1, 
                        "members": {st.session_state.user_id: {"name": u_name, "ready": False}},
                        "selected_modules": MODULES.copy(),
                        "availability": {},
                        "norm_candidates": [],
                    }
                    st.session_state.room_name = r_name
                    st.session_state.user_name = u_name
                    st.rerun()

def render_sidebar(room: dict) -> None:
    is_host = room["host_id"] == st.session_state.user_id
    
    with st.sidebar:
        st.subheader(f"🏠 所在房間：{st.session_state.room_name}")
        if st.button("🔄 重新整理抓取最新資料"):
            st.rerun()
            
        st.divider()
        st.markdown("**👥 成員狀態**")
        all_ready = True
        for uid, info in room["members"].items():
            role = "👑 主持人" if uid == room["host_id"] else "👤 組員"
            status = "✅ 準備完成" if info["ready"] else "⏳ 填寫中"
            if not info["ready"]:
                all_ready = False
            st.write(f"{role} {info['name']} - {status}")

        st.divider()
        if room["step"] == 1:
            my_ready = room["members"][st.session_state.user_id]["ready"]
            if st.checkbox("☑️ 我已完成我的部分", value=my_ready):
                if not my_ready:
                    room["members"][st.session_state.user_id]["ready"] = True
                    st.rerun()
            else:
                if my_ready:
                    room["members"][st.session_state.user_id]["ready"] = False
                    st.rerun()
            
            if is_host:
                st.markdown("**👑 主持人控制介面**")
                if all_ready:
                    st.success("所有成員皆已填寫完成！")
                else:
                    st.warning("尚有成員未完成填寫。")
                    
                if st.button("推進到下一步 (結果彙整)", type="primary", use_container_width=True):
                    room["step"] = 2
                    st.rerun()
        else:
            st.success("目前為：結果統整階段 (無法再更改設定)")
            if is_host:
                st.markdown("**👑 主持人控制介面**")
                if st.button("返回填寫階段", use_container_width=True):
                    room["step"] = 1
                    for uid in room["members"]:
                        room["members"][uid]["ready"] = False
                    st.rerun()
        
        st.divider()
        if st.button("離開房間", use_container_width=True):
            st.session_state.room_name = None
            st.rerun()

def render_schedule_module(room: dict) -> None:
    st.subheader("🗓️ 討論時間安排")
    
    start_day = date.today()
    day_count = 5
    slots = half_hour_slots()
    days = [start_day + timedelta(days=offset) for offset in range(day_count)]
    
    if "temp_slots" not in st.session_state:
        st.session_state.temp_slots = set(room["availability"].get(st.session_state.user_id, []))
        
    if room["step"] == 1:
        st.markdown(f"#### ✍️ 請 {st.session_state.user_name} 勾選您可以參與的時間")
        
        st.write("💡 **一鍵快捷填寫：**")
        c1, c2, c3 = st.columns(3)
        if c1.button("📅 平日晚上全部勾選 (18:00後)", use_container_width=True):
            for d in days:
                if d.weekday() < 5: 
                    for s in slots:
                        if s >= "18:00":
                            st.session_state.temp_slots.add(f"{d.isoformat()} {s}")
            st.rerun()
            
        if c2.button("🏖️ 假日整天全部勾選", use_container_width=True):
            for d in days:
                if d.weekday() >= 5: 
                    for s in slots:
                        st.session_state.temp_slots.add(f"{d.isoformat()} {s}")
            st.rerun()
            
        if c3.button("❌ 清除我勾選的所有時段", use_container_width=True):
            st.session_state.temp_slots.clear()
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
                    is_checked = slot_key in st.session_state.temp_slots
                    
                    if s < "12:00":
                        col = cols_morning[m_idx % 4]
                        m_idx += 1
                    elif s < "18:00":
                        col = cols_afternoon[a_idx % 4]
                        a_idx += 1
                    else:
                        col = cols_evening[e_idx % 4]
                        e_idx += 1
                        
                    if col.checkbox(s, value=is_checked, key=f"cb_{slot_key}"):
                        st.session_state.temp_slots.add(slot_key)
                    else:
                        st.session_state.temp_slots.discard(slot_key)
                        
        if st.button("💾 儲存並同步我的時間", type="primary", use_container_width=True):
            room["availability"][st.session_state.user_id] = list(st.session_state.temp_slots)
            st.success("您的可參與時段已成功同步至小組房間！")

    st.markdown("#### 📊 小組時間熱點統整 (When2meet 模式)")
    completed = len([uid for uid in room["members"] if uid in room["availability"]])
    st.progress(completed / len(room["members"]), text=f"填寫進度：已填寫 {completed} / {len(room['members'])} 人")

    if room["availability"]:
        grid_data = {}
        for s in slots:
            grid_data[s] = {}
            for d in days:
                slot_key = f"{d.isoformat()} {s}"
                avail_members = [
                    room["members"][uid]["name"] for uid in room["members"]
                    if slot_key in room["availability"].get(uid, [])
                ]
                grid_data[s][d.strftime("%m/%d (%a)")] = avail_members

        flat_counts = []
        for s in slots:
            for d in days:
                sk = f"{d.isoformat()} {s}"
                members = [uid for uid in room["members"] if sk in room["availability"].get(uid, [])]
                if len(members) >= majority_count(room):
                    flat_counts.append((d.strftime("%m/%d (%a)"), s, len(members), [room["members"][uid]["name"] for uid in members]))
        
        flat_counts.sort(key=lambda x: (-x[2], x[0], x[1]))

        if flat_counts:
            st.markdown("🏆 **最推薦開會時段（滿足多數人）：**")
            for idx, (d_str, s_str, count, names) in enumerate(flat_counts[:3]):
                st.success(f"**第 {idx+1} 推薦**：{d_str} {s_str} ｜ 共 **{count}** 人有空 ({'、'.join(names)})")
        else:
            st.info(f"💡 目前尚未有時段達到過半數門檻 ({majority_count(room)}人)。")

        st.markdown("**📅 完整時間縱覽表（綠色越深代表越多人有空）：**")
        
        html_table = "<table style='width:100%; border-collapse:collapse; text-align:center; font-family:sans-serif;'>"
        html_table += "<tr style='background-color:#f1f3f5; font-weight:bold;'><th style='border:1px solid #dee2e6; padding:8px;'>時間</th>"
        for d in days:
            html_table += f"<th style='border:1px solid #dee2e6; padding:8px;'>{d.strftime('%m/%d<br>(%a)')}</th>"
        html_table += "</tr>"
        
        total_m = len(room["members"])
        for s in slots:
            html_table += f"<tr><td style='border:1px solid #dee2e6; font-weight:bold; background-color:#f8f9fa; padding:4px; font-size:13px;'>{s}</td>"
            for d in days:
                d_str = d.strftime("%m/%d (%a)")
                avail_list = grid_data[s][d_str]
                count = len(avail_list)
                
                alpha = count / total_m if total_m else 0
                bg_color = f"rgba(40, 167, 69, {alpha * 0.75})" if count > 0 else "transparent"
                text_color = "#ffffff" if alpha > 0.5 else "#212529"
                
                names_tooltip = "&#10;".join(avail_list) if avail_list else "無人有空"
                
                html_table += f"<td title='有空的人：&#10;{names_tooltip}' style='border:1px solid #dee2e6; background-color:{bg_color}; color:{text_color}; padding:6px; font-size:12px; cursor:help;'>"
                html_table += f"<b>{count}/{total_m}</b>"
                html_table += "</td>"
            html_table += "</tr>"
        html_table += "</table>"
        
        st.components.v1.html(html_table, height=500, scroller=True)
    else:
        st.info("尚無組員填寫時間資料。")

def render_norms_module(room: dict) -> None:
    st.subheader("⚖️ 合作規範系統")
    
    if room["step"] == 1:
        with st.form("norm_form", clear_on_submit=True):
            raw_text = st.text_area("匿名規範徵集", placeholder="例如：群組訊息應該在 3 小時內回覆、開會要準時", height=100)
            submitted = st.form_submit_button("送出並整合")

        if submitted:
            ok, message = add_norm_candidate(room, raw_text)
            if ok:
                st.success(message)
            else:
                st.warning(message)

    st.markdown("**📜 背書區**")
    if not room["norm_candidates"]:
        st.info("尚無合格條文。")
        
    for candidate in room["norm_candidates"]:
        status, support_count, opponent_count, preferred_option = candidate_status(room, candidate)
        with st.container(border=True):
            st.caption(candidate["category"])
            st.write(candidate["standard"])
            cols = st.columns([1, 1, 1, 2])
            cols[0].metric("支持", support_count)
            cols[1].metric("不可行", opponent_count)
            cols[2].metric("狀態", status)
            if preferred_option is not None:
                cols[3].metric("目前偏好參數", f"{preferred_option} 小時")
            elif candidate["options"]:
                cols[3].metric("參數選項", "、".join(f"{item} 小時" for item in sorted(candidate["options"])))
            else:
                cols[3].write("無參數衝突")

            if room["step"] == 1:
                action_cols = st.columns([1, 1, 2])
                if candidate["options"]:
                    option = action_cols[2].selectbox(
                        "支持時選擇偏好時間",
                        sorted(candidate["options"] | set(TIME_OPTIONS)),
                        key=f"pref_{candidate['id']}",
                        format_func=lambda value: f"{value} 小時",
                    )
                else:
                    option = None
                
                has_supported = st.session_state.user_id in candidate["supporters"]
                has_opposed = st.session_state.user_id in candidate["opponents"]
                
                if action_cols[0].button("已支持" if has_supported else "支持", key=f"support_{candidate['id']}", type="primary" if has_supported else "secondary"):
                    candidate["supporters"].add(st.session_state.user_id)
                    candidate["opponents"].discard(st.session_state.user_id)
                    if option is not None:
                        candidate["preferences"][st.session_state.user_id] = option
                    st.rerun()
                if action_cols[1].button("已投不可行" if has_opposed else "不可行", key=f"oppose_{candidate['id']}", type="primary" if has_opposed else "secondary"):
                    candidate["opponents"].add(st.session_state.user_id)
                    candidate["supporters"].discard(st.session_state.user_id)
                    candidate["preferences"].pop(st.session_state.user_id, None)
                    st.rerun()

    active_items, pending_items = [], []
    for candidate in room["norm_candidates"]:
        status, support_count, opponent_count, preferred_option = candidate_status(room, candidate)
        record = (candidate, status, support_count, opponent_count, preferred_option)
        if status == "Active":
            active_items.append(record)
        elif status == "待議":
            pending_items.append(record)

    st.markdown("**✅ 正式公約區**")
    if not active_items:
        st.info("尚無達成高共識的條文。")
    for candidate, _, support_count, _, preferred_option in active_items:
        text = candidate["standard"]
        if preferred_option is not None:
            text = re.sub(r"\d{1,2}\s*小時", f"{preferred_option} 小時", text)
        st.success(f"Active ｜ {text} ｜ 支持 {support_count}/{len(room['members'])}")

    st.markdown("**⚠️ 待議區**")
    if not pending_items:
        st.info("目前沒有低支持度提案。")
    for candidate, _, support_count, opponent_count, _ in pending_items:
        st.warning(f"待議 ｜ {candidate['standard']} ｜ 支持 {support_count}、不可行 {opponent_count}。")

# ==========================================
# 主程式進入點
# ==========================================
def main() -> None:
    ensure_state()
    
    if st.session_state.room_name is None:
        render_auth()
    else:
        room = DB.get(st.session_state.room_name)
        if not room:
            st.error("房間已關閉或資料遺失，請重新登入。")
            st.session_state.room_name = None
            st.rerun()
            return
            
        st.title(f"小組協作平台")
        if room["step"] == 2:
            st.info("📢 目前為「結果統整階段」，您可檢視最終定案內容。若需修改，請主持人退回填寫階段。")
            
        render_sidebar(room)
        
        # 依照剩餘模組依序渲染
        if "討論時間安排" in room["selected_modules"]:
            render_schedule_module(room)
            st.divider()
        if "合作規範系統" in room["selected_modules"]:
            render_norms_module(room)

if __name__ == "__main__":
    main()