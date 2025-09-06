import pandas as pd
import streamlit as st
from logic import generate_groups

st.title("PlanMaker")

participants_file = st.file_uploader("Wgraj plik z zapisami")
schedule_file = st.file_uploader("Wgraj plik z planem lekcji")
bells_file = st.file_uploader("Wgraj plik z dzwonkami")


earliest_hour = st.text_input("Najwcześniejsza godzina zajęć")
latest_hour = st.text_input("Najpóźniejsza godzina zajęć")
slot_len = st.number_input("Długość zajęć (w minutach)", min_value=1, max_value=60, step=1)

if st.button("Generuj grupy"):
    groups = generate_groups(earliest_hour, latest_hour, slot_len, 15, bells_file, schedule_file, participants_file)
    groups_table = pd.DataFrame.from_dict(groups, orient='index').transpose()
    st.dataframe(groups_table)


