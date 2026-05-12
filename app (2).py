import streamlit as st
import pandas as pd
from collections import defaultdict

st.title("📅 小組時間協調系統")

if "responses" not in st.session_state:
    st.session_state.responses = []

def generate_time_slots():
    slots = []
    hour, minute = 8, 0

    while hour < 22:
        start = f"{hour:02d}:{minute:02d}"
        minute += 30
        if minute == 60:
            minute = 0
            hour += 1
        end = f"{hour:02d}:{minute:02d}"
        slots.append(f"{start} - {end}")
    return slots

TIME_SLOTS = generate_time_slots()

with st.form("form"):
    name = st.text_input("姓名")
    meeting_type = st.radio("討論方式", ["實體", "線上"])

    st.write("選擇可參與時段")
    selected = []

    for slot in TIME_SLOTS:
        if st.checkbox(slot):
            selected.append(slot)

    submit = st.form_submit_button("送出")

    if submit and name:
        st.session_state.responses.append({
            "name": name,
            "type": meeting_type,
            "slots": selected
        })
        st.success("已送出")

st.subheader("推薦時段")

total = len(st.session_state.responses)

if total > 0:
    counter = defaultdict(int)

    for r in st.session_state.responses:
        for s in r["slots"]:
            counter[s] += 1

    result = [
        (k, v) for k, v in counter.items()
        if v > total / 2
    ]

    result.sort(key=lambda x: x[1], reverse=True)

    st.dataframe(pd.DataFrame(result, columns=["時段", "人數"]))
else:
    st.info("尚無資料")