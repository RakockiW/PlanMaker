import pandas as pd
import streamlit as st

from logic import GroupScheduler


def move_member(slot_str, member_key, group_key):
    member = st.session_state.get(member_key)
    target = st.session_state.get(group_key)

    if not member:
        st.warning("Nie wybrano uczestnika.")
        return
    if not target:
        st.warning("Nie wybrano grupy docelowej.")
        return
    if target == slot_str:
        st.info("Uczestnik już jest w tej grupie.")
        return

    scheduler = st.session_state.get("scheduler")
    if not scheduler:
        st.error("Brak scheduler w session_state.")
        return

    success, msg, conflict = scheduler.move_member(member, target, from_slot_str=slot_str, allow_conflict=True)

    st.session_state["groups"]["groups"] = scheduler.groups

    if not success:
        st.error(msg)
    else:
        if conflict:
            st.warning(msg)
        else:
            st.success(msg)

st.set_page_config(layout="wide")
st.title("PlanMaker")

participants_file = st.file_uploader("Wgraj plik z zapisami")
schedule_file = st.file_uploader("Wgraj plik z planem lekcji")
bells_file = st.file_uploader("Wgraj plik z dzwonkami")

earliest_hour = st.text_input("Najwcześniejsza godzina zajęć", "8:00")
latest_hour = st.text_input("Najpóźniejsza godzina zajęć", "18:00")
slot_len = st.number_input("Długość zajęć (w minutach)", min_value=1, max_value=60, step=1, value=60)
included_days = st.multiselect("Dni zajęć", ["pon", "wt", "sr", "czw", "pt"], default=["pon", "wt", "sr", "czw", "pt"])

if "scheduler" not in st.session_state:
    st.session_state["scheduler"] = None
if "groups" not in st.session_state:
    st.session_state["groups"] = None

if st.button("Generuj grupy"):
    scheduler = GroupScheduler(
        bells_csv=bells_file,
        schedule_csv=schedule_file,
        participants_csv=participants_file,
        earliest_hour=earliest_hour,
        latest_hour=latest_hour,
        included_days=included_days)
    groups, wait_times = scheduler.generate_groups()
    st.session_state["scheduler"] = scheduler
    st.session_state["groups"] = {"groups": groups, "wait_times": wait_times}


if st.session_state["groups"]:
    scheduler = st.session_state["scheduler"]
    groups = st.session_state["groups"]["groups"]
    wait_times = st.session_state["groups"]["wait_times"]

    group_keys = list(groups.keys())


    group_items = list(groups.items())
    for i in range(0, len(group_items), 3):
        row = group_items[i:i + 3]

        left_right_ratio = 1
        middle_ratio = 3
        layout = [left_right_ratio] + [middle_ratio] * len(row) + [left_right_ratio]
        cols = st.columns(layout)

        content_cols = cols[1:1 + len(row)]

        for col, (slot_str, members) in zip(content_cols, row):
            rows = []
            for participant in members:
                wait, when = scheduler.wait_times.get(participant, {}).get(slot_str, (0, ""))
                rows.append({
                    "Uczestnik": participant,
                    "Czas oczekiwania": f"{wait} min {when}"
                })
            df = pd.DataFrame(rows)

            col.subheader(f"Grupa: {slot_str}")
            col.dataframe(df, use_container_width=True, height=300)

            inner_left, inner_mid, inner_right = col.columns([1, 2, 1])
            safe_slot = slot_str.replace(" ", "_").replace(":", "-")
            member_key = f"{safe_slot}_select_member"
            group_key = f"{safe_slot}_select_group"
            button_key = f"{safe_slot}_move_button"

            chosen_member = inner_mid.selectbox("Wybierz uczestnika", members, key=member_key)
            chosen_group = inner_mid.selectbox("Wybierz grupę", list(groups.keys()), key=group_key)
            inner_mid.button(
                "Przenieś",
                key=button_key,
                on_click=move_member,
                args=(slot_str, member_key, group_key)
            )
            if "member_moves" not in st.session_state:
                st.session_state["member_moves"] = {}
            st.session_state["member_moves"][slot_str] = {
                "member": chosen_member,
                "to_group": chosen_group
            }
