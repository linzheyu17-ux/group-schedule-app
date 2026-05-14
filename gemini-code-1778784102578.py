from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from math import floor
import re
from uuid import uuid4

import streamlit as st

MODULES = ["討論時間安排", "方向提案", "分工規劃", "合作規範系統"]
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

def build_slot_keys(days: list[date], slots: list[str]) -> list[str]:
    return [f"{day.isoformat()} {slot}" for day in days for slot in slots]

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
                        "step": 1, # 1: 填寫與討論階段, 2: 結果統整階段
                        "members": {st.session_state.user_id: {"name": u_name, "ready": False}},
                        "selected_modules": MODULES.copy(),
                        "availability": {},
                        "direction_votes": defaultdict(set),
                        "norm_candidates": [],
                        "custom_tasks": [],
                        "task_assignments": {}
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
    
    if room["step"] == 1:
        cols = st.columns([1, 1, 2])
        start_day = cols[0].date_input("起始日期", value=date.today())
        day_count = cols[1].number_input("天數", min_value=1, max_value=14, value=5, step=1)
        mode = cols[2].segmented_control("討論形式", options=["實體討論", "線上討論", "皆可"], default="皆可")

        days = [start_day + timedelta(days=offset) for offset in range(day_count)]
        slots = half_hour_slots()
        slot_keys = build_slot_keys(days, slots)
        
        current_my_slots = room["availability"].get(st.session_state.user_id, set())
        selected_slots = st.multiselect(
            f"請 {st.session_state.user_name} 勾選您可參與的時段（每半小時為單位）",
            slot_keys,
            default=sorted(current_my_slots),
            placeholder="選擇所有可開會時間",
        )
        if st.button("儲存我的時段"):
            room["availability"][st.session_state.user_id] = set(selected_slots)
            st.success("您的可參與時段已儲存。")

    completed = len([uid for uid in room["members"] if uid in room["availability"]])
    st.progress(completed / len(room["members"]), text=f"填寫進度：已填寫 {completed} / {len(room['members'])} 人")

    # 計算推薦時間 (無論在哪個 Step 都顯示)
    if room["availability"]:
        # 重建所有的 slot_keys 來計算交集
        all_slots_ever_selected = set()
        for slots in room["availability"].values():
            all_slots_ever_selected.update(slots)
            
        counts = []
        for slot_key in all_slots_ever_selected:
            available_members = [
                room["members"][uid]["name"] for uid in room["members"]
                if slot_key in room["availability"].get(uid, set())
            ]
            if len(available_members) >= majority_count(room):
                counts.append((slot_key, len(available_members), available_members))

        st.markdown("**🌟 推薦討論時間 (達多數門檻)**")
        if not counts:
            st.info(f"目前沒有超過半數成員可參與的時段。門檻：{majority_count(room)} 人。")
        else:
            counts.sort(key=lambda item: (-item[1], item[0]))
            for slot_key, count, member_names in counts:
                names = "、".join(member_names)
                st.write(f"**{slot_key}** ｜ {count} 人可參與：{names}")

def render_direction_module(room: dict) -> None:
    st.subheader("🧭 方向提案")
    proposals = [
        "先完成資料蒐集，再收斂簡報主軸",
        "先決定研究問題，再分配案例與文獻",
        "以老師評分標準為核心建立簡報架構",
    ]
    
    if room["step"] == 1:
        st.write("請選擇您支持的推進方向：")
        for proposal in proposals:
            cols = st.columns([4, 1])
            cols[0].write(proposal)
            btn_text = "收回支持" if st.session_state.user_id in room["direction_votes"][proposal] else "支持"
            if cols[1].button(btn_text, key=f"vote_{proposal}"):
                if st.session_state.user_id in room["direction_votes"][proposal]:
                    room["direction_votes"][proposal].remove(st.session_state.user_id)
                else:
                    room["direction_votes"][proposal].add(st.session_state.user_id)
                st.rerun()

    st.markdown("**📊 目前排序**")
    for proposal in sorted(proposals, key=lambda item: -len(room["direction_votes"][item])):
        votes = len(room["direction_votes"][proposal])
        st.write(f"**{proposal}**：{votes} 票")

def render_tasks_module(room: dict) -> None:
    st.subheader("📋 分工規劃")
    
    if room["step"] == 1:
        with st.form("task_form", clear_on_submit=True):
            task_name = st.text_input("新增任務", placeholder="例如：製作簡報第 3-5 頁")
            due_day = st.date_input("截止日期", value=date.today() + timedelta(days=3))
            added = st.form_submit_button("新增任務")
        if added and task_name.strip():
            room["custom_tasks"].append({"id": uuid4().hex, "name": task_name.strip(), "due": due_day})

    if room["custom_tasks"]:
        member_options = {info["name"]: uid for uid, info in room["members"].items()}
        labels = ["未分配"] + list(member_options.keys())
        
        for task in room["custom_tasks"]:
            cols = st.columns([2.5, 1.5, 2])
            cols[0].write(task["name"])
            cols[1].write(task["due"].isoformat())
            
            current_uid = room["task_assignments"].get(task["id"])
            current_name = room["members"].get(current_uid, {}).get("name") if current_uid else "未分配"
            default_index = labels.index(current_name) if current_name in labels else 0
            
            if room["step"] == 1:
                assignee_label = cols[2].selectbox("負責人", labels, index=default_index, key=f"task_{task['id']}")
                if assignee_label != "未分配":
                    room["task_assignments"][task["id"]] = member_options[assignee_label]
                elif task["id"] in room["task_assignments"]:
                    del room["task_assignments"][task["id"]]
            else:
                cols[2].write(f"負責人：**{current_name}**")
    else:
        st.info("目前尚無任務，請新增。")

def render_norms_module(room: dict) -> None:
    st.subheader("⚖️ 合作規範系統")
    
    if room["step"] == 1:
        with st.form("norm_form", clear_on_submit=True):
            raw_text = st.text_area("匿名徵集", placeholder="例如：群組訊息應該在 3 小時內回覆、開會要準時", height=100)
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
                
                # 按鈕狀態判定
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
        
        # 依照模組依序渲染
        if "討論時間安排" in room["selected_modules"]:
            render_schedule_module(room)
            st.divider()
        if "方向提案" in room["selected_modules"]:
            render_direction_module(room)
            st.divider()
        if "分工規劃" in room["selected_modules"]:
            render_tasks_module(room)
            st.divider()
        if "合作規範系統" in room["selected_modules"]:
            render_norms_module(room)

if __name__ == "__main__":
    main()