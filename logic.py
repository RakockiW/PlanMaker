from typing import Dict, List, Tuple, Set, Union, IO
import pandas as pd
import networkx as nx

Slot = Tuple[str, int, int]           # (day, start_min, end_min)
ParticipantSlots = Dict[str, List[Slot]]
ClassTimes = Dict[str, Dict[str, Tuple[int,int]]]



def parse_time(t: str) -> int:
    h, m = map(int, t.strip().split(":"))
    return 60*h + m

def slot_to_str(slot: Slot) -> str:
    day, s, e = slot
    return f"{day} {s//60:02d}:{s%60:02d}-{e//60:02d}:{e%60:02d}"

def str_to_slot(s: str) -> Slot:
    # "day HH:MM-HH:MM"
    day, times = s.split(" ", 1)
    start_s, end_s = times.split("-")
    sh, sm = map(int, start_s.split(":"))
    eh, em = map(int, end_s.split(":"))
    return day, sh * 60 + sm, eh * 60 + em

LARGE_PENALTY = 10**6



def read_bells(file: Union[str, IO]) -> Dict[int, str]:
    df = pd.read_csv(file, header=None, names=["Nr", "Godziny"])
    return dict(zip(df["Nr"].astype(int), df["Godziny"]))

def read_schedule(bells: Dict[int, str], file: Union[str, IO]) -> Dict[str, Dict[str, str]]:
    df = pd.read_csv(file).dropna(how="all")
    sched = df.set_index("Klasa").to_dict(orient="index")
    for cls, days in sched.items():
        for day, rng in list(days.items()):
            if pd.isna(rng) or str(rng).strip() == "":
                continue
            start_idx, end_idx = map(int, str(rng).split("-"))
            start_time = bells[start_idx].split(" - ")[0].strip()
            end_time   = bells[end_idx].split(" - ")[1].strip()
            days[day] = f"{start_time}-{end_time}"
    return sched



def generate_slots(day: str, start_min: int, end_min: int,
                   slot_len: int = 60, step: int = 15,
                   earliest_start: int = 8*60) -> List[Slot]:

    slots: List[Slot] = []
    t = max(start_min, earliest_start)
    while t + slot_len <= end_min:
        slots.append((day, t, t + slot_len))
        t += step
    return slots


def build_participant_slots(schedule: Dict[str,Dict[str,str]],
                            participants_csv: Union[str, IO],
                            earliest_hour: str = "08:00",
                            latest_hour: str = "18:00",
                            slot_len: int = 60,
                            step: int = 15) -> Tuple[ParticipantSlots, ClassTimes]:

    earliest_min = parse_time(earliest_hour)
    latest_min = parse_time(latest_hour)

    people = pd.read_csv(participants_csv)
    participant_slots: ParticipantSlots = {}
    class_times: ClassTimes = {}

    for _, r in people.iterrows():
        name = f"{r['Imię']} {r['Nazwisko']} {r['Klasa']}"
        cls = r['Klasa']
        participant_slots[name] = []
        class_times[name] = {}
        if cls not in schedule:
            continue
        for day, rng in schedule[cls].items():
            if pd.isna(rng) or str(rng).strip() == "":
                continue
            start_s, end_s = rng.split("-")
            class_start = parse_time(start_s)
            class_end = parse_time(end_s)
            class_times[name][day] = (class_start, class_end)

            if class_start > earliest_min:
                participant_slots[name].extend(
                    generate_slots(day, earliest_min, class_start, slot_len, step, earliest_min)
                )
            if class_end < latest_min:
                participant_slots[name].extend(
                    generate_slots(day, class_end, latest_min, slot_len, step, earliest_min)
                )

    return participant_slots, class_times



def compute_wait_minutes(person: str, slot: Slot, class_times: ClassTimes) -> int:

    day, slot_start, slot_end = slot
    times = class_times.get(person, {})
    if day not in times:
        return 0
    class_start, class_end = times[day]
    if slot_start >= class_end:
        return slot_start - class_end
    if slot_end <= class_start:
        return 0
    return LARGE_PENALTY



def assign_groups_globally_optimal(participant_slots: ParticipantSlots,
                                   class_times: ClassTimes,
                                   min_size: int = 5,
                                   max_size: int = 12) -> Dict[str, List[str]]:

    slot_to_candidates: Dict[Slot, Set[str]] = {}
    for person, slots in participant_slots.items():
        for slot in slots:
            slot_to_candidates.setdefault(slot, set()).add(person)

    candidate_slots = {s: set(p) for s, p in slot_to_candidates.items() if len(p) >= min_size}
    if not candidate_slots:
        return {}

    participants = list(participant_slots.keys())

    while True:
        G = nx.DiGraph()
        source, sink = "S", "T"
        for p in participants:
            G.add_edge(source, p, capacity=1)
        for slot, cand in candidate_slots.items():
            slot_node = slot_to_str(slot)
            for p in cand:
                wait = compute_wait_minutes(p, slot, class_times)
                if wait >= LARGE_PENALTY:
                    continue
                G.add_edge(p, slot_node, capacity=1)
        for slot in candidate_slots.keys():
            G.add_edge(slot_to_str(slot), sink, capacity=max_size)

        F = nx.maximum_flow_value(G, source, sink)
        if F == 0:
            return {}

        Gc = nx.DiGraph()
        Gc.add_node(source); Gc.add_node(sink)
        for p in participants:
            Gc.add_node(p)
        for slot in candidate_slots.keys():
            Gc.add_node(slot_to_str(slot))

        for p in participants:
            Gc.add_edge(source, p, capacity=1, weight=0)
        for slot, cand in candidate_slots.items():
            slot_node = slot_to_str(slot)
            for p in cand:
                wait = compute_wait_minutes(p, slot, class_times)
                if wait >= LARGE_PENALTY:
                    continue
                Gc.add_edge(p, slot_node, capacity=1, weight=int(wait))
        for slot in candidate_slots.keys():
            Gc.add_edge(slot_to_str(slot), sink, capacity=max_size, weight=0)

        for n in Gc.nodes():
            Gc.nodes[n]['demand'] = 0
        Gc.nodes[source]['demand'] = -int(F)
        Gc.nodes[sink]['demand'] = int(F)

        flow_dict = nx.algorithms.flow.min_cost_flow(Gc)

        slot_counts: Dict[str,int] = {}
        slot_members: Dict[str, List[str]] = {}
        for p in participants:
            outs = flow_dict.get(p, {})
            for slot_node, f in outs.items():
                if f and f > 0:
                    slot_counts.setdefault(slot_node, 0)
                    slot_counts[slot_node] += f
                    slot_members.setdefault(slot_node, []).append(p)

        slots_to_remove = [sn for sn, cnt in slot_counts.items() if cnt < min_size]
        if not slots_to_remove:
            final = {sn: members for sn, members in slot_members.items() if len(members) >= min_size}
            return dict(sorted(final.items(), key=lambda x: x[0]))

        removed = set()
        for sn in slots_to_remove:
            tup = str_to_slot(sn)
            removed.add(tup)
        for r in removed:
            candidate_slots.pop(r, None)
        if not candidate_slots:
            return {}

def generate_groups(earliest_hour: str,
                    latest_hour: str,
                    slot_len: int,
                    step: int,
                    bells_csv: Union[str, IO],
                    schedule_csv: Union[str, IO],
                    participants_csv: Union[str, IO]) -> Dict[str, List[str]]:

    bells = read_bells(bells_csv)
    schedule = read_schedule(bells, schedule_csv)

    participant_slots, class_times = build_participant_slots(schedule,
                                                             participants_csv,
                                                             earliest_hour,
                                                             latest_hour,
                                                             slot_len,
                                                             step)

    groups = assign_groups_globally_optimal(participant_slots, class_times, min_size=5, max_size=12)

    return groups

