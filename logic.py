import pandas as pd
import networkx as nx
from typing import Dict, List, Tuple, Set, Union, IO, Optional

Slot = Tuple[str, int, int]  # (day, start_min, end_min)


class GroupScheduler:
    LARGE_PENALTY = 10**6

    def __init__(self, bells_csv: str, schedule_csv: str, participants_csv: str,
                 earliest_hour: str = "08:00", latest_hour: str = "18:00",
                 slot_len: int = 60, step: int = 15,
                 min_size: int = 5, max_size: int = 12, included_days: Optional[List[str]] = None,):

        self.bells_csv = bells_csv
        self.schedule_csv = schedule_csv
        self.participants_csv = participants_csv
        self.earliest_hour = earliest_hour
        self.latest_hour = latest_hour
        self.included_days = included_days
        self.slot_len = slot_len
        self.step = step
        self.min_size = min_size
        self.max_size = max_size

        self.bells = {}
        self.schedule = {}
        self.participant_slots = {}
        self.wait_times = {}
        self.class_times = {}
        self.groups = {}
        self.unassigned = []

    @staticmethod
    def parse_time(t: str) -> int:
        h, m = map(int, t.strip().split(":"))
        return 60*h + m

    @staticmethod
    def slot_to_str(slot: Slot) -> str:
        day, s, e = slot
        return f"{day} {s//60:02d}:{s%60:02d}-{e//60:02d}:{e%60:02d}"

    @staticmethod
    def str_to_slot(s: str) -> Slot:
        day, times = s.split(" ", 1)
        start_s, end_s = times.split("-")
        sh, sm = map(int, start_s.split(":"))
        eh, em = map(int, end_s.split(":"))
        return day, sh * 60 + sm, eh * 60 + em

    def read_bells(self):
        df = pd.read_csv(self.bells_csv, header=None, names=["Nr", "Godziny"])
        self.bells = dict(zip(df["Nr"].astype(int), df["Godziny"]))

    def read_schedule(self):
        df = pd.read_csv(self.schedule_csv).dropna(how="all")
        sched = df.set_index("Klasa").to_dict(orient="index")
        for cls, days in sched.items():
            for day, rng in list(days.items()):
                if pd.isna(rng) or str(rng).strip() == "":
                    continue
                start_idx, end_idx = map(int, str(rng).split("-"))
                start_time = self.bells[start_idx].split(" - ")[0].strip()
                end_time   = self.bells[end_idx].split(" - ")[1].strip()
                days[day] = f"{start_time}-{end_time}"
        self.schedule = sched

    def generate_slots(self, day: str, start_min: int, end_min: int) -> List[Slot]:
        slots = []
        t = max(start_min, self.parse_time(self.earliest_hour))
        while t + self.slot_len <= end_min:
            slots.append((day, t, t + self.slot_len))
            t += self.step
        return slots

    def build_participant_slots(self):
        earliest_min = self.parse_time(self.earliest_hour)
        latest_min = self.parse_time(self.latest_hour)

        people = pd.read_csv(self.participants_csv)
        for _, r in people.iterrows():
            name = f"{r['Imię']} {r['Nazwisko']} {r['Klasa']}"
            cls = r['Klasa']
            self.participant_slots[name] = []
            self.class_times[name] = {}
            if cls not in self.schedule:
                continue
            for day, rng in self.schedule[cls].items():
                if pd.isna(rng) or str(rng).strip() == "" or day not in self.included_days:
                    continue
                start_s, end_s = rng.split("-")
                class_start = self.parse_time(start_s)
                class_end = self.parse_time(end_s)
                self.class_times[name][day] = (class_start, class_end)

                if class_start > earliest_min:
                    self.participant_slots[name].extend(
                        self.generate_slots(day, earliest_min, class_start)
                    )
                if class_end < latest_min:
                    self.participant_slots[name].extend(
                        self.generate_slots(day, class_end, latest_min)
                    )

    def compute_wait_minutes(self, person: str, slot: Slot) -> (int, str):
        day, slot_start, slot_end = slot
        times = self.class_times.get(person, {})
        if day not in times:
            return 0
        class_start, class_end = times[day]

        if slot_end <= class_start:
            return class_start - slot_end, "na start lekcji"
        elif slot_start >= class_end:
            return slot_start - class_end, "na start zajęć"
        else:
            return self.LARGE_PENALTY, "konflikt!"

    def assign_groups(self):

        slot_to_candidates: Dict[Slot, Set[str]] = {}
        for person, slots in self.participant_slots.items():
            for slot in slots:
                slot_to_candidates.setdefault(slot, set()).add(person)

        candidate_slots = {s: set(p) for s, p in slot_to_candidates.items() if len(p) >= self.min_size}
        if not candidate_slots:
            return {}

        participants = list(self.participant_slots.keys())

        while True:
            G = nx.DiGraph()
            source, sink = "S", "T"
            for p in participants:
                G.add_edge(source, p, capacity=1)
            for slot, cand in candidate_slots.items():
                slot_node = self.slot_to_str(slot)
                for p in cand:
                    wait, when = self.compute_wait_minutes(p, slot)
                    if wait >= self.LARGE_PENALTY:
                        continue
                    G.add_edge(p, slot_node, capacity=1)
            for slot in candidate_slots.keys():
                G.add_edge(self.slot_to_str(slot), sink, capacity=self.max_size)

            F = nx.maximum_flow_value(G, source, sink)
            if F == 0:
                return {}

            Gc = nx.DiGraph()
            Gc.add_node(source); Gc.add_node(sink)
            for p in participants:
                Gc.add_node(p)
            for slot in candidate_slots.keys():
                Gc.add_node(self.slot_to_str(slot))

            for p in participants:
                Gc.add_edge(source, p, capacity=1, weight=0)
            for slot, cand in candidate_slots.items():
                slot_node = self.slot_to_str(slot)
                for p in cand:
                    wait, when = self.compute_wait_minutes(p, slot)
                    self.wait_times.setdefault(p, {})[slot_node] = (wait, when)
                    if wait >= self.LARGE_PENALTY:
                        continue
                    Gc.add_edge(p, slot_node, capacity=1, weight=int(wait))
            for slot in candidate_slots.keys():
                Gc.add_edge(self.slot_to_str(slot), sink, capacity=self.max_size, weight=0)

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

            slots_to_remove = [sn for sn, cnt in slot_counts.items() if cnt < self.min_size]
            if not slots_to_remove:
                final = {sn: members for sn, members in slot_members.items() if len(members) >= self.min_size}
                return dict(sorted(final.items(), key=lambda x: x[0]))

            removed = set()
            for sn in slots_to_remove:
                tup = self.str_to_slot(sn)
                removed.add(tup)
            for r in removed:
                candidate_slots.pop(r, None)
            if not candidate_slots:
                return {}

    def move_member(self, member: str, to_slot_str: str, from_slot_str: Optional[str] = None,
                    allow_conflict: bool = True) -> Tuple[bool, str, bool]:

        if member is None or to_slot_str is None:
            return False, "Niepoprawne argumenty (member lub to_slot_str są puste).", False

        try:
            to_slot = self.str_to_slot(to_slot_str)
        except Exception as e:
            return False, f"Niepoprawny format to_slot_str: {to_slot_str}", False

        wait, when = self.compute_wait_minutes(member, to_slot)
        conflict = (wait >= self.LARGE_PENALTY)

        if conflict and not allow_conflict:
            return False, f"Przeniesienie zablokowane: konflikt ({when}).", True

        target_members = self.groups.get(to_slot_str, [])
        if len(target_members) >= self.max_size and member not in target_members:
            return False, f"Grupa docelowa '{to_slot_str}' jest pełna (max_size={self.max_size}).", False

        source_slot = None
        if from_slot_str:
            if from_slot_str in self.groups and member in self.groups[from_slot_str]:
                source_slot = from_slot_str
            else:
                return False, f"Uczestnik '{member}' nie należy do grupy źródłowej '{from_slot_str}'.", False
        else:
            for s, members in self.groups.items():
                if member in members:
                    source_slot = s
                    break

        if source_slot:
            if member in self.groups.get(source_slot, []):
                self.groups[source_slot].remove(member)

            if len(self.groups.get(source_slot, [])) < self.min_size:
                remaining = self.groups.pop(source_slot, [])
                for p in remaining:
                    if p in self.wait_times:
                        self.wait_times[p].pop(source_slot, None)
                    if p not in self.unassigned:
                        self.unassigned.append(p)

        self.groups.setdefault(to_slot_str, [])
        if member not in self.groups[to_slot_str]:
            self.groups[to_slot_str].append(member)

        self.wait_times.setdefault(member, {})
        self.wait_times[member][to_slot_str] = (wait, when)

        if conflict:
            return True, f"Przeniesiono '{member}' do '{to_slot_str}', ale wykryto konflikt: {when}.", True
        else:
            return True, f"Przeniesiono '{member}' do '{to_slot_str}'.", False

    def get_assigned_wait_time(self) -> list[Tuple[str, int, str]]:
        assigned_wait_time = []
        for slot_str, members in self.groups.items():
            for participant in members:
                wait, when = self.wait_times.get(participant, {}).get(slot_str, 0)
                assigned_wait_time.append((participant, slot_str, wait, when))

        return assigned_wait_time

    def generate_groups(self):

        self.read_bells()
        self.read_schedule()

        self.build_participant_slots()

        self.groups = self.assign_groups()
        return self.groups, self.get_assigned_wait_time()

