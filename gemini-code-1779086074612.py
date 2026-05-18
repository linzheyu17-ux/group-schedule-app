from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from math import floor
import re
from uuid import uuid4

import streamlit as st


ROLES = ["組長", "紀錄者", "簡報負責人", "資料蒐集", "時間管理", "組員"]
AVATARS = ["🟦", "🟩", "🟨", "🟧", "🟪", "⭐", "🌿", "📌"]
# 精簡模組：只留下討論時間與合作規範
MODULES = ["討論時間安排", "合作規範系統"]
TIME_OPTIONS = [1, 2, 3, 6, 12, 24, 48]


st.set_page_config(
    page_title="小組協作平台",
    page_icon="✅",
    layout="wide",
)


def ensure_state() -> None:
    defaults = {
        "members": [],
        "availability": {},
        # 修正 Bug：直接在初始化時就預設啟用這兩個核心模組
        "selected_modules": ["討論時間安排", "合作規範系統"],
        "norm_candidates": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def member_label(member: dict) -> str:
    display_name = member["nickname"] or member["name"]
    return f'{member["avatar"]} {display_name}｜{member["role"]}'


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
    st.caption("建立組員名單，即可同步進行開會時間協調與合作公約匿名徵集背書。")


def render_member_setup() -> None:
    st.subheader("1. 基本資料設定")
    with st.form("member_form", clear_on_submit=True):
        cols = st.columns([1.2, 1.2, 1, 1])
        name = cols[0].text_input("姓名", placeholder="例如：王小明")
        nickname = cols[1].text_input("暱稱", placeholder="可留空")
        role = cols[2].selectbox("小組身份", ROLES)
        avatar = cols[3].selectbox("預設頭貼", AVATARS)
        submitted = st.form_submit_button("加入小組", use_container_width=True)

    if submitted:
        if not name.strip() and not nickname.strip():
            st.warning("請至少填寫姓名或暱稱。")
        else:
            st.session_state.members.append(
                {
                    "id": uuid4().hex,
                    "name": name.strip() or nickname.strip(),
                    "nickname": nickname.strip(),
                    "role": role,
                    "avatar": avatar,
                }
            )
            st.success("成員已加入。")

    st.metric("目前已加入人數", len(st.session_state.members))
    if st.session_state.members:
        for member in st.session_state.members:
            cols = st.columns([5, 1])
            cols[0].write(member_label(member))
            if cols[1].button("移除", key=f"remove_{member['id']}", use_container_width=True):
                st.session_state.members = [
                    item for item in st.session_state.members if item["id"] != member["id"]
                ]
                st.session_state.availability.pop(member["id"], None)
                st.rerun()
    else:
        st.info("尚未有成員加入。")


def render_module_picker() -> None:
    st.subheader("2. 啟用功能模組")
    st.session_state.selected_modules = st.multiselect(
        "若需要調整，可由成員自由增減啟用的模組項目。",
        MODULES,
        default=st.session_state.selected_modules,
    )


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

    # 初始化該成員在 session_state 中的暫存集合
    temp_key = f"temp_slots_{selected_member_id}"
    if temp_key not in st.session_state:
        st.session_state[temp_key] = set(st.session_state.availability.get(selected_member_id, set()))

    st.markdown(f"#### ✍️ 請勾選 **{selected_label}** 可以配合的時段")
    
    # 快捷功能區
    st.write("💡 **快捷填寫按鈕：**")
    c1, c2, c3 = st.columns(3)
    if c1.button("📅 平日晚上全部勾選 (18:00後)", key=f"quick_p_{selected_member_id}", use_container_width=True):
        for d in days:
            if d.weekday() < 5:  # 週一至週五
                for s in slots:
                    if s >= "18:00":
                        st.session_state[temp_key].add(f"{d.isoformat()} {s}")
        st.rerun()
        
    if c2.button("🏖️ 假日整天全部勾選", key=f"quick_h_{selected_member_id}", use_container_width=True):
        for d in days:
            if d.weekday() >= 5:  # 週六週日
                for s in slots:
                    st.session_state[temp_key].add(f"{d.isoformat()} {s}")
        st.rerun()
        
    if c3.button("❌ 清除該成員所有勾選", key=f"quick_c_{selected_member_id}", use_container_width=True):
        st.session_state[temp_key].clear()
        st.rerun()

    # 日曆課表網格網頁化 (Tabs)
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
                else:
                    col = cols_evening[e_idx % 4]
                    e_idx += 1
                    
                if col.checkbox(s, value=is_checked, key=f"cb_{slot_key}_{selected_member_id}"):
                    st.session_state[temp_key].add(slot_key)
                else:
                    st.session_state[temp_key].discard(slot_key)

    if st.button("💾 儲存該成員時間資料", type="primary", use_container_width=True):
        st.session_state.availability[selected_member_id] = set(st.session_state[temp_key])
        st.success(f"{selected_label} 的可參與時段已儲存並同步！")

    # ==================== 統計與視覺化熱點區 ====================
    st.divider()
    st.markdown("#### 📊 小組時間熱點統整 (When2meet 模式)")
    completed = len([mid for mid in active_member_ids() if mid in st.session_state.availability and st.session_state.availability[mid]])
    st.progress(completed / len(st.session_state.members), text=f"填寫進度：已填寫 {completed} / {len(st.session_state.members)} 人")

    if st.session_state.availability:
        # 建立結構化矩陣資料
        grid_data = {}
        for s in slots:
            grid_data[s] = {}
            for d in days:
                slot_key = f"{d.isoformat()} {s}"
                avail_members = [
                    member for member in st.session_state.members
                    if slot_key in st.session_state.availability.get(member["id"], set())
                ]
                grid_data[s][d.strftime("%m/%d (%a)")] = avail_members

        # 找出符合門檻的最佳時段
        counts = []
        for d in days:
            for s in slots:
                slot_key = f"{d.isoformat()} {s}"
                avail_members = grid_data[s][d.strftime("%m/%d (%a)")]
                if len(avail_members) >= majority_count():
                    counts.append((d.strftime("%m/%d (%a)"), s, len(avail_members), avail_members))

        st.markdown("**🏆 推薦開會時段（滿足過半數成員）：**")
        if not counts:
            st.info(f"💡 目前尚未有時段達到過半數門檻 ({majority_count()}人)。")
        else:
            counts.sort(key=lambda item: (-item[2], item[0], item[1]))
            for idx, (d_str, s_str, count, members) in enumerate(counts[:3]):
                names = "、".join(member["name"] for member in members)
                st.success(f"**第 {idx+1} 推薦**：{d_str} {s_str} ｜ 形式：{mode} ｜ 共 **{count}** 人有空 ({names})")

        # 繪製視覺化 HTML 熱點表格
        st.markdown("**📅 完整時間縱覽表（綠色越深代表越多人有空，滑鼠移上去格子上可看名單）：**")
        
        html_table = "<table style='width:100%; border-collapse:collapse; text-align:center; font-family:sans-serif;'>"
        html_table += "<tr style='background-color:#f1f3f5; font-weight:bold;'><th style='border:1px solid #dee2e6; padding:8px;'>時間</th>"
        for d in days:
            html_table += f"<th style='border:1px solid #dee2e6; padding:8px;'>{d.strftime('%m/%d<br>(%a)')}</th>"
        html_table += "</tr>"
        
        total_m = len(st.session_state.members)
        for s in slots:
            html_table += f"<tr><td style='border:1px solid #dee2e6; font-weight:bold; background-color:#f8f9fa; padding:4px; font-size:13px;'>{s}</td>"
            for d in days:
                d_str = d.strftime("%m/%d (%a)")
                avail_list = grid_data[s][d_str]
                count = len(avail_list)
                
                # 計算顏色深淺 (Green Alpha)
                alpha = count / total_m if total_m else 0
                bg_color = f"rgba(40, 167, 69, {alpha * 0.75})" if count > 0 else "transparent"
                text_color = "#ffffff" if alpha > 0.5 else "#212529"
                
                names_tooltip = "&#10;".join(m["name"] + f"({m['role']})" for m in avail_list) if avail_list else "無人有空"
                
                html_table += f"<td title='有空的人：&#10;{names_tooltip}' style='border:1px solid #dee2e6; background-color:{bg_color}; color:{text_color}; padding:6px; font-size:12px; cursor:help;'>"
                html_table += f"<b>{count}/{total_m}</b>"
                html_table += "</td>"
            html_table += "</tr>"
        html_table += "</table>"
        
        st.components.v1.html(html_table, height=500, scroller=True)


def render_norms_module() -> None:
    st.subheader("⚖️ 合作規範系統")
    if not st.session_state.members:
        st.info("請先加入成員，系統才能計算支持率。")

    with st.form("norm_form", clear_on_submit=True):
        raw_text = st.text_area(
            "匿名規範徵集",
            placeholder="例如：群組訊息應該在 3 小時內回覆、開會要準時、分工需提前回報進度",
            height=100,
        )
        submitted = st.form_submit_button("送出並整合")

    if submitted:
        ok, message = add_norm_candidate(raw_text)
        if ok:
            st.success(message)
        else:
            st.warning(message)

    member_options = {member_label(member): member["id"] for member in st.session_state.members}
    voter_id = None
    if member_options:
        voter_label = st.selectbox("背書成員", list(member_options.keys()), key="norm_voter")
        voter_id = member_options[voter_label]

    st.markdown("**📜 背書區**")
    if not st.session_state.norm_candidates:
        st.info("尚無合格條文。")
    for candidate in st.session_state.norm_candidates:
        status, support_count, opponent_count, preferred_option = candidate_status(candidate)
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

            if voter_id:
                action_cols = st.columns([1, 1, 2])
                if candidate["options"]:
                    option = action_cols[2].selectbox(
                        "支持時選擇偏好時間",
                        sorted(candidate["options"] | set(TIME_OPTIONS)),
                        key=f"pref_{candidate['id']}_{voter_id}",
                        format_func=lambda value: f"{value} 小時",
                    )
                else:
                    option = None
                if action_cols[0].button("支持", key=f"support_{candidate['id']}_{voter_id}"):
                    candidate["supporters"].add(voter_id)
                    candidate["opponents"].discard(voter_id)
                    if option is not None:
                        candidate["preferences"][voter_id] = option
                    st.rerun()
                if action_cols[1].button("不可行", key=f"oppose_{candidate['id']}_{voter_id}"):
                    candidate["opponents"].add(voter_id)
                    candidate["supporters"].discard(voter_id)
                    candidate["preferences"].pop(voter_id, None)
                    st.rerun()

    active_items = []
    pending_items = []
    for candidate in st.session_state.norm_candidates:
        status, support_count, opponent_count, preferred_option = candidate_status(candidate)
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
        st.success(f"Active ｜ {text} ｜ 支持 {support_count}/{len(st.session_state.members)}")

    st.markdown("**⚠️ 待議區**")
    if not pending_items:
        st.info("目前沒有低支持度提案。")
    for candidate, _, support_count, opponent_count, _ in pending_items:
        st.warning(
            f"待議 ｜ {candidate['standard']} ｜ 支持 {support_count}、不可行 {opponent_count}。"
        )


def main() -> None:
    ensure_state()
    render_header()
    left, right = st.columns([1, 2])
    with left:
        render_member_setup()
        render_module_picker()
    with right:
        # 只保留與選取相符的兩大模組渲染
        if "討論時間安排" in st.session_state.selected_modules:
            render_schedule_module()
            st.divider()
        if "合作規範系統" in st.session_state.selected_modules:
            render_norms_module()


if __name__ == "__main__":
    main()