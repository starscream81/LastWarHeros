import os
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime

import streamlit as st
from supabase import create_client, Client

# --------------------------------------------------
# App config
# --------------------------------------------------
st.set_page_config(page_title="LastWarHeros v2", page_icon="🛡️", layout="wide")

# --------------------------------------------------
# Supabase client
# --------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_supabase() -> Client:
    url = None
    key = None
    try:
        if "supabase" in st.secrets:
            sec = st.secrets["supabase"]
            url = sec.get("url")
            key = sec.get("anon_key")
    except Exception:
        pass
    url = url or os.environ.get("SUPABASE_URL")
    key = key or os.environ.get("SUPABASE_ANON_KEY")
    if not url or not key:
        st.error("Missing Supabase credentials. Add to .streamlit/secrets.toml or set SUPABASE_URL / SUPABASE_ANON_KEY.")
        st.stop()
    return create_client(url, key)

sb: Client = get_supabase()

# Connection banner
try:
    sb.table("buildings_kv").select("key").limit(1).execute()
except Exception:
    st.warning("⚠️ Supabase connection failed. Check URL and key.")


# --------------------------------------------------
# Data model: Buildings (KV) — keep user's order
# --------------------------------------------------
from collections import OrderedDict

base_buildings = [
    "HQ", "Wall",
    "Tech Center 1-3",
    "Barracks 1-4", "Barrack 2",
    "Drill Ground 1-4",
    "Hospital 1-4", "Emergency Center",
    "Alert Tower", "Recon Plane 1-3",
    "Coin Vault", "Food Warehouse", "Iron Warehouse",
    "Gold Mine 1-5", "Iron Mine 1-5", "Farmland 1-5", "Oil Well 1-5",
    "Smelter 1-5", "Training Base 1-5", "Material Workshop 1-5",
    "Alliance Center", "Builder's Hut", "Tavern", "Technical Institute",
    "Drone Parts Workshop", "Chip Lab", "Component Factory", "Gear Factory",
]

def expand_ranges_in_order(names: list[str]) -> list[str]:
    out: list[str] = []
    for n in names:
        parts = n.rsplit(" ", 1)
        if len(parts) == 2 and "-" in parts[1]:
            head, rng = parts[0], parts[1]
            try:
                lo, hi = [int(x) for x in rng.split("-")]
                for i in range(lo, hi + 1):
                    out.append(f"{head} {i}")
            except Exception:
                out.append(n)
        else:
            out.append(n)
    return out

DEFAULT_BUILDINGS: list[str] = expand_ranges_in_order(base_buildings)

# --------------------------------------------------
# KV helpers
# --------------------------------------------------
# --- KV helpers for small settings like team_* ---
def kv_get(key: str, default: str = "") -> str:
    try:
        res = sb.table("buildings_kv").select("key,value").eq("key", key).maybe_single().execute()
        row = res.data
        return row["value"] if row and row.get("value") is not None else default
    except Exception:
        return default

def kv_set(key: str, value: str) -> None:
    try:
        sb.table("buildings_kv").upsert({"key": key, "value": str(value)}).execute()
    except Exception as e:
        st.toast(f"Save failed for {key}: {e}", icon="⚠️")


def kv_bulk_read(keys: list[str]) -> dict[str, dict[str, Any]]:
    """Return mapping in the *same order* as `keys`."""
    # Fetch all existing rows at once
    rows = sb.table("buildings_kv").select("key,value,updated_at").in_("key", keys).execute().data or []
    by_key = {r["key"]: r for r in rows}
    ordered: dict[str, dict[str, Any]] = OrderedDict()
    for k in keys:
        r = by_key.get(k)
        if r:
            ordered[k] = {"value": r.get("value"), "updated_at": r.get("updated_at")}
        else:
            ordered[k] = {"value": None, "updated_at": None}
    return ordered

def kv_bulk_upsert(rows: List[Dict[str, Any]]) -> None:
    if rows:
        sb.table("buildings_kv").upsert(rows).execute()


def to_int(v: Optional[str]) -> int:
    try:
        if v is None or v == "":
            return 0
        return int(v)
    except Exception:
        return 0

# ----- Buildings tracking (🔨 upgrading, 🧱 next) -----
def bldg_tracking_load_sets() -> tuple[set, set]:
    """Return (upgrading_set, next_set) from DB."""
    try:
        res = sb.table("buildings_tracking").select("name, upgrading, next").execute()
        rows = res.data or []
        upg = {r["name"] for r in rows if r.get("upgrading")}
        nxt = {r["name"] for r in rows if r.get("next")}
        return upg, nxt
    except Exception:
        return set(), set()

def bldg_tracking_save_from_editor(edited_df):
    """Upsert building tracking states from a grid that has 'name', 'hammer', 'brick' columns."""
    payload = []
    for _, r in edited_df.iterrows():
        nm = str(r.get("name", "")).strip()
        if not nm:
            continue
        payload.append({
            "name": nm,
            "upgrading": bool(r.get("hammer", False)),  # 🔨
            "next":      bool(r.get("brick",  False)),  # 🧱
        })
    if payload:
        sb.table("buildings_tracking").upsert(payload, on_conflict="name").execute()
        
# --------- Fast loaders (cached) ---------
@st.cache_data(ttl=5)
def kv_read_many(keys: list[str]) -> dict[str, str]:
    # one query instead of many kv_get calls
    res = sb.table("buildings_kv").select("key,value").in_("key", keys).execute()
    rows = res.data or []
    m = {r["key"]: r.get("value") if r.get("value") is not None else "0" for r in rows}
    # ensure every requested key exists
    for k in keys:
        m.setdefault(k, "0")
    return m

@st.cache_data(ttl=5)
def bldg_tracking_load_sets_cached() -> tuple[set, set]:
    res = sb.table("buildings_tracking").select("name, upgrading, next").execute()
    rows = res.data or []
    upg = {r["name"] for r in rows if r.get("upgrading")}
    nxt = {r["name"] for r in rows if r.get("next")}
    return upg, nxt

# --------------------------------------------------
# UI helpers
# --------------------------------------------------

def buildings_table(load: dict[str, dict[str, Any]]):
    import pandas as pd

    # Build rows in the exact DEFAULT_BUILDINGS order
    data = [{"Name": name, "Level": to_int(load[name]["value"])} for name in load.keys()]

    df = pd.DataFrame(data)  # keep provided order; do NOT sort here

    st.caption("Edit levels below. Changes are not saved until you click 'Save changes'.")
    edited = st.data_editor(
        df,
        num_rows="fixed",
        use_container_width=True,
        column_config={
            "Name": st.column_config.Column(disabled=True),
            "Level": st.column_config.NumberColumn(min_value=0, max_value=200, step=1),
        },
        key="bld_table",
    )

    # Diff against original
    changed_rows: List[Dict[str, Any]] = []
    for idx, row in edited.iterrows():
        name = row["Name"]
        new_level = int(row["Level"]) if row["Level"] is not None else 0
        old_level = to_int(load[name]["value"]) if name in load else 0
        if new_level != old_level:
            changed_rows.append({"key": name, "value": str(new_level)})

    col1, col2 = st.columns([1,1])
    with col1:
        if st.button("Save changes", type="primary", use_container_width=True, disabled=(len(changed_rows) == 0)):
            try:
                kv_bulk_upsert(changed_rows)
                st.success(f"Saved {len(changed_rows)} change(s).")
                st.session_state.pop("bld_table", None)  # force reload on next run
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")
    with col2:
        if st.button("Reload from Supabase", use_container_width=True):
            st.session_state.pop("bld_table", None)
            st.rerun()

# --------------------------------------------------
# Navigation
# --------------------------------------------------
PAGES = ["Dashboard", "Buildings", "Heroes", "Add or Update Hero", "Research"]
with st.sidebar:
    st.title("LastWarHeros")
    page = st.radio("Navigate", PAGES, index=0)  # start on Dashboard

# --------------------------------------------------
# Pages
# --------------------------------------------------
# --- Drop-in helpers for Dashboard ---
import math
import pandas as pd
import streamlit as st

# Expect: sb (Supabase client) and DEFAULT_BUILDINGS + kv_bulk_read() already in file

# Flexible resolver that can read exact keys and common aliases/typos
ALIASES = {
    "oil wall": "Oil Well",
    "coil vault": "Coin Vault",
    "farm warehouse": "Food Warehouse",
    "tactical institute": "Technical Institute",
    "training grounds": "Drill Ground",    # user wording vs our stored names
}

# For grouped series like "Tech Center 1-3"
SERIES = {
    "Tech Center": list(range(1, 4)),
    "Barracks": list(range(1, 4+1)),
    "Hospital": list(range(1, 4+1)),
    "Drill Ground": list(range(1, 4+1)),
    "Recon Plane": list(range(1, 3+1)),
    "Gold Mine": list(range(1, 5+1)),
    "Iron Mine": list(range(1, 5+1)),
    "Farmland": list(range(1, 5+1)),
    "Oil Well": list(range(1, 5+1)),
    "Smelter": list(range(1, 5+1)),
    "Training Base": list(range(1, 5+1)),
    "Material Workshop": list(range(1, 5+1)),
}

# Some singletons with exact keys in KV
SINGLES = [
    "HQ","Wall","Emergency Center","Alert Tower","Coin Vault","Food Warehouse","Iron Warehouse",
    "Alliance Center","Builder's Hut","Tavern","Technical Institute","Drone Parts Workshop","Chip Lab","Component Factory","Gear Factory"
]


def get_level(kv: dict, name: str) -> int:
    # resolve alias
    n = ALIASES.get(name.lower(), name)
    row = kv.get(n)
    if row is None:
        return 0
    v = row.get("value")
    try:
        return int(v) if v not in (None, "") else 0
    except Exception:
        try:
            return int(float(str(v)))
        except Exception:
            return 0


def max_series(kv: dict, base: str, rng: list[int]) -> int:
    vals = [get_level(kv, f"{base} {i}") for i in rng]
    return max(vals) if vals else 0


def sum_series(kv: dict, base: str, rng: list[int]) -> int:
    return sum(get_level(kv, f"{base} {i}") for i in rng)


# centers mentioned in spec; if missing from KV, they will stay 0 gracefully
CENTER_NAMES = ["Tank Center", "Aircraft Center", "Missile Center"]

def max_centers(kv: dict) -> int:
    return max([get_level(kv, c) for c in CENTER_NAMES] or [0])


# Simple gradient utility for percentage chips

def pct_chip(pct: float, label: str) -> str:
    p = max(0, min(100, int(round(pct))))
    # red to green gradient with black text for readability
    return (
        f"<div style='display:inline-block;padding:6px 10px;border-radius:12px;"
        f"background:linear-gradient(90deg, rgba(255,120,120,1) 0%, rgba(120,200,120,1) {p}%, rgba(235,235,235,1) {p}%);"
        f"color:black;font-weight:700;box-shadow:0 1px 4px rgba(0,0,0,0.08);'>"
        f"{label}{p}%"
        f"</div>"
    )

# --- DASHBOARD --------------------------------------------------------------
if page == "Dashboard":
    import pandas as pd  # ensure available in this scope

    cols = st.columns([1, 3])

    # Load buildings once
    kv = kv_bulk_read(DEFAULT_BUILDINGS)
    hq = get_level(kv, "HQ")

    # total hero power
    try:
        res = sb.table("heroes").select("power").execute()
        arr = pd.to_numeric(pd.DataFrame(res.data or []).get("power"), errors="coerce")
        total_power = int(arr.fillna(0).sum())
    except Exception:
        total_power = 0

    formatted_power = f"{total_power:,}"

    with cols[0]:
        try:
            st.image("frog.png", width=160)
        except Exception:
            st.write(":frog: (frog.png not found)")

    with cols[1]:
        html = f"""
        <div style='display:flex; align-items:center; height:160px;'>
            <div style='margin-left:15px;'>
                <h2 style='margin:0; font-weight:700;'>Shōckwave [FER]</h2>
                <div style='font-size:1.1rem; margin-top:6px;'>
                    <strong>HQ Level:</strong>
                    <span style='font-weight:700; font-size:1.2rem;'>{hq}</span>
                    &nbsp;&nbsp;&nbsp;
                    <strong>Total Hero Power:</strong>
                    <span style='font-weight:700; font-size:1.2rem;'>{formatted_power}</span>
                </div>
            </div>
        </div>
        """
        st.markdown(html, unsafe_allow_html=True)
    st.divider()
    st.subheader("Teams")

    team_opts = ["Tank", "Air", "Missile", "Mixed"]

    # prime from KV
    for i in range(1, 4):
        tkey = f"team_{i}_type"
        pkey = f"team_{i}_power"
        if tkey not in st.session_state:
            st.session_state[tkey] = kv_get(f"team{i}_type", "Tank")
        if pkey not in st.session_state:
            st.session_state[pkey] = kv_get(f"team{i}_power", "")

    def _save_type(i: int):
        kv_set(f"team{i}_type", st.session_state[f"team_{i}_type"])

    def _save_power(i: int):
        cur = st.session_state[f"team_{i}_power"].strip()
        st.session_state[f"team_{i}_power"] = cur
        kv_set(f"team{i}_power", cur)

    for i in range(1, 4):
        sel_col, pow_col, _spacer = st.columns([1.5, 1.3, 10])

        with sel_col:
            # IMPORTANT: no index/value passed — widget reads from session_state
            st.selectbox(
                f"Team {i}",
                team_opts,
                key=f"team_{i}_type",
                on_change=_save_type,
                args=(i,),
            )

        with pow_col:
            st.text_input(
                "Power",
                key=f"team_{i}_power",
                max_chars=10,
                placeholder="120.46M",
                on_change=_save_power,
                args=(i,),
            )

    st.divider()
    st.subheader("Buildings")

    # --- First row (4 columns): raw values ---
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown("**Wall**")
        st.write(get_level(kv, "Wall"))
        st.markdown("**Tech Center**")
        st.write(max_series(kv, "Tech Center", SERIES["Tech Center"]))
        st.markdown("**Tank/Air/Missile Center**")
        st.write(max_centers(kv))
    with c2:
        st.markdown("**Barracks**")
        st.write(max_series(kv, "Barracks", SERIES["Barracks"]))
        st.markdown("**Hospital**")
        st.write(max_series(kv, "Hospital", SERIES["Hospital"]))
        st.markdown("**Training Grounds**")
        st.write(max_series(kv, "Drill Ground", SERIES["Drill Ground"]))
    with c3:
        st.empty()
    with c4:
        st.empty()

    st.write("")

    # --- Second row: percentages vs HQ with gradient chips ---
    c1, c2, c3, c4 = st.columns(4)

    def pct_of_hq_sum(base: str, series_key: str) -> float:
        if hq <= 0:
            return 0.0
        rng = SERIES[series_key]
        total = sum_series(kv, base, rng)
        denom = len(rng) * hq
        return (total / denom) * 100.0 if denom > 0 else 0.0

    def pct_of_hq_single(name: str) -> float:
        if hq <= 0:
            return 0.0
        return (get_level(kv, name) / hq) * 100.0

    with c1:
        st.markdown("**Tech Center**")
        st.markdown(pct_chip(pct_of_hq_sum("Tech Center", "Tech Center"), ""), unsafe_allow_html=True)
        st.markdown("**Tank/Air/Missile**")
        p_centers = 0.0
        present = [c for c in CENTER_NAMES if c in kv]
        if hq > 0 and present:
            s = sum(get_level(kv, c) for c in present)
            p_centers = (s / (len(present) * hq)) * 100.0
        st.markdown(pct_chip(p_centers, ""), unsafe_allow_html=True)
        st.markdown("**Barracks**")
        st.markdown(pct_chip(pct_of_hq_sum("Barracks", "Barracks"), ""), unsafe_allow_html=True)
        st.markdown("**Hospital**")
        st.markdown(pct_chip(pct_of_hq_sum("Hospital", "Hospital"), ""), unsafe_allow_html=True)
        st.markdown("**Training Grounds**")
        st.markdown(pct_chip(pct_of_hq_sum("Drill Ground", "Drill Ground"), ""), unsafe_allow_html=True)
        st.markdown("**Emergency Center**")
        st.markdown(pct_chip(pct_of_hq_single("Emergency Center"), ""), unsafe_allow_html=True)
        st.markdown("**Squads**")
        st.markdown(pct_chip(pct_of_hq_sum("Drill Ground", "Drill Ground"), ""), unsafe_allow_html=True)
        st.markdown("**Alert Tower**")
        st.markdown(pct_chip(pct_of_hq_single("Alert Tower"), ""), unsafe_allow_html=True)
        st.markdown("**Recon Plane**")
        st.markdown(pct_chip(pct_of_hq_sum("Recon Plane", "Recon Plane"), ""), unsafe_allow_html=True)

    with c2:
        st.markdown("**Coin Vault**")
        st.markdown(pct_chip(pct_of_hq_single("Coin Vault"), ""), unsafe_allow_html=True)
        st.markdown("**Iron Warehouse**")
        st.markdown(pct_chip(pct_of_hq_single("Iron Warehouse"), ""), unsafe_allow_html=True)
        st.markdown("**Food Warehouse**")
        st.markdown(pct_chip(pct_of_hq_single("Food Warehouse"), ""), unsafe_allow_html=True)
        st.markdown("**Oil Well**")
        st.markdown(pct_chip(pct_of_hq_sum("Oil Well", "Oil Well"), ""), unsafe_allow_html=True)
        st.markdown("**Gold Mine**")
        st.markdown(pct_chip(pct_of_hq_sum("Gold Mine", "Gold Mine"), ""), unsafe_allow_html=True)
        st.markdown("**Iron Mine**")
        st.markdown(pct_chip(pct_of_hq_sum("Iron Mine", "Iron Mine"), ""), unsafe_allow_html=True)
        st.markdown("**Farmland**")
        st.markdown(pct_chip(pct_of_hq_sum("Farmland", "Farmland"), ""), unsafe_allow_html=True)
        st.markdown("**Smelter**")
        st.markdown(pct_chip(pct_of_hq_sum("Smelter", "Smelter"), ""), unsafe_allow_html=True)

    with c3:
        st.markdown("**Alliance Center**")
        st.markdown(pct_chip(pct_of_hq_single("Alliance Center"), ""), unsafe_allow_html=True)
        st.markdown("**Builder's Hut**")
        st.markdown(pct_chip(pct_of_hq_single("Builder's Hut"), ""), unsafe_allow_html=True)
        st.markdown("**Tavern**")
        st.markdown(pct_chip(pct_of_hq_single("Tavern"), ""), unsafe_allow_html=True)
        st.markdown("**Technical Institute**")
        st.markdown(pct_chip(pct_of_hq_single("Technical Institute"), ""), unsafe_allow_html=True)
        st.markdown("**Training Base**")
        st.markdown(pct_chip(pct_of_hq_sum("Training Base", "Training Base"), ""), unsafe_allow_html=True)

    with c4:
        st.markdown("**Drone Parts Workshop**")
        st.markdown(pct_chip(pct_of_hq_single("Drone Parts Workshop"), ""), unsafe_allow_html=True)
        st.markdown("**Chip Lab**")
        st.markdown(pct_chip(pct_of_hq_single("Chip Lab"), ""), unsafe_allow_html=True)
        st.markdown("**Component Factory**")
        st.markdown(pct_chip(pct_of_hq_single("Component Factory"), ""), unsafe_allow_html=True)
        st.markdown("**Gear Factory**")
        st.markdown(pct_chip(pct_of_hq_single("Gear Factory"), ""), unsafe_allow_html=True)
        st.markdown("**Material Workshop**")
        st.markdown(pct_chip(pct_of_hq_sum("Material Workshop", "Material Workshop"), ""), unsafe_allow_html=True)
# --- END DASHBOARD ----------------------------------------------------------


# ============================
# Buildings page
# ============================
elif page == "Buildings":
    import pandas as pd

    st.header("Buildings")
    st.write("Standard table. Only updates rows you actually change. No undo/redo.")

    # --- fast read: all levels at once, cached briefly ---
    current_map = kv_read_many(DEFAULT_BUILDINGS)

    rows = [{"name": b, "level": int(current_map.get(b, "0") or 0)} for b in DEFAULT_BUILDINGS]
    df = pd.DataFrame(rows)

    # --- fast read: tracking sets, cached briefly ---
    up_set, next_set = bldg_tracking_load_sets_cached()

    # inject 🔨 / 🧱
    df["hammer"] = df["name"].astype(str).isin(up_set)
    df["brick"]  = df["name"].astype(str).isin(next_set)

    # status line
    up_count, next_count = int(df["hammer"].sum()), int(df["brick"].sum())
    if up_count or next_count:
        st.caption(f"🔨 {up_count} upgrading | 🧱 {next_count} next")

    # editor
    editor_cols = ["hammer", "brick", "name", "level"]
    show = df[editor_cols].copy()

    edited = st.data_editor(
        show,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "hammer": st.column_config.CheckboxColumn("🔨"),
            "brick":  st.column_config.CheckboxColumn("🧱"),
            "name":   st.column_config.TextColumn("Building", width="large", required=True),
            "level":  st.column_config.NumberColumn("Level", min_value=0, max_value=60, step=1),
        },
        hide_index=True,
        key="buildings_editor",
    )

    # --- only upsert tracking if it changed ---
    new_up   = set(edited.loc[edited["hammer"], "name"]) if "hammer" in edited.columns else set()
    new_next = set(edited.loc[edited["brick"],  "name"]) if "brick"  in edited.columns else set()

    if new_up != up_set or new_next != next_set:
        payload = []
        # union of all names involved
        all_names = set(edited["name"])
        for nm in all_names:
            payload.append({
                "name": nm,
                "upgrading": nm in new_up,
                "next":      nm in new_next,
            })
        sb.table("buildings_tracking").upsert(payload, on_conflict="name").execute()
        # clear tiny caches so UI reflects immediately
        bldg_tracking_load_sets_cached.clear()

    # optional badges
    any_hammer, any_brick = bool(new_up), bool(new_next)
    if any_hammer or any_brick:
        badges_html = f"""
        <style>
        @keyframes pulse {{ 0%{{transform:scale(1)}} 50%{{transform:scale(1.07)}} 100%{{transform:scale(1)}} }}
        .b-badges{{display:flex;justify-content:flex-end;margin-top:6px;gap:.5rem}}
        .b-badge{{display:flex;align-items:center;gap:.35rem;font-weight:700;animation:pulse 1s infinite}}
        .b-badge.dim{{opacity:.85}}
        </style>
        <div class="b-badges">
          {('<div class="b-badge">🔨<span>Upgrading</span></div>' if any_hammer else '')}
          {('<div class="b-badge dim">🧱<span>Next up</span></div>' if any_brick else '')}
        </div>
        """
        st.markdown(badges_html, unsafe_allow_html=True)

    # save / reload buttons for levels
    colA, colB = st.columns(2)
    with colA:
        if st.button("Save changes", use_container_width=True):
            try:
                to_save = edited[["name", "level"]].copy()
                changes = []
                for _, r in to_save.iterrows():
                    key = r["name"]
                    lvl = int(r.get("level", 0) or 0)
                    if str(current_map.get(key, "")) != str(lvl):
                        changes.append({"key": key, "value": str(lvl)})
                if changes:
                    sb.table("buildings_kv").upsert(changes).execute()
                    kv_read_many.clear()   # clear cache so reload shows new values
                st.success("Saved")
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")
    with colB:
        if st.button("Reload from Supabase", use_container_width=True):
            kv_read_many.clear()
            st.rerun()

# ============================
# Heros page
# ============================
elif page == "Heroes":
    st.header("Heroes")
    st.write("Sorted by Power (desc). Role-based highlights + green 5-star override + clean numbers.")

    try:
        cols = (
            "id,name,level,power,"
            "rail_gun,rail_gun_stars,armor,armor_stars,data_chip,data_chip_stars,radar,radar_stars,"
            "weapon,weapon_level,max_skill_level,skill1,skill2,skill3,"
            "type,role,team,updated_at"
        )

        res = sb.table("heroes").select(cols).order("power", desc=True).execute()
        rows = res.data or []
        if not rows:
            st.warning("No heroes found in table 'heroes'.")
        else:
            import pandas as pd
            df = pd.DataFrame(rows)

            # numeric coercions
            num_cols = ["power","level","rail_gun","armor","data_chip","radar",
                        "weapon_level","max_skill_level","skill1","skill2","skill3"]
            for c in num_cols:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")

            # final sort by power desc
            if "power" in df.columns:
                df = df.sort_values("power", ascending=False, na_position="last")

            display_cols = [c for c in [
                "name","power","level","type","role","team",
                "rail_gun","rail_gun_stars","armor","armor_stars",
                "data_chip","data_chip_stars","radar","radar_stars",
                "weapon","weapon_level","max_skill_level","skill1","skill2","skill3",
                "updated_at"
            ] if c in df.columns]
            df_show = df[display_cols].copy()

            # Role → orange mapping
            role_orange = {
                "attack":  ["rail_gun","data_chip"],
                "defense": ["armor","radar"],
                "support": ["rail_gun","radar"],
            }
            # Base/stat pairs for 5-star override
            star_pairs = [
                ("rail_gun", "rail_gun_stars"),
                ("armor", "armor_stars"),
                ("data_chip", "data_chip_stars"),
                ("radar", "radar_stars"),
            ]

            ORANGE = "background-color: orange; font-weight: 600;"
            GREEN  = "background-color: #22c55e; color: black; font-weight: 700;"

            def style_cells(df_in: pd.DataFrame) -> pd.DataFrame:
                styles = pd.DataFrame('', index=df_in.index, columns=df_in.columns)

                # 1) apply role-based orange
                roles = df_in.get("role")
                if roles is not None:
                    roles = roles.astype(str).str.lower().fillna("")
                    for idx, role in roles.items():
                        cols_to_paint = role_orange.get(role, [])
                        for col in cols_to_paint:
                            if col in styles.columns:
                                styles.loc[idx, col] = ORANGE
                            # paint *_stars alongside base if present
                            star_col = f"{col}_stars"
                            if star_col in styles.columns:
                                styles.loc[idx, star_col] = ORANGE

                # 2) override with green for 5-star rows
                for base, stars in star_pairs:
                    if stars in df_in.columns:
                        # stars columns are text in schema; coerce to number
                        s_num = pd.to_numeric(df_in[stars], errors="coerce")
                        five_mask = s_num >= 5  # catches 5 or 5.0
                        idxs = df_in.index[five_mask.fillna(False)]
                        for i in idxs:
                            if base in styles.columns:
                                styles.loc[i, base] = GREEN
                            if stars in styles.columns:
                                styles.loc[i, stars] = GREEN

                return styles

            # clean number formatting (no long decimal tails)
            def fmt_int(x):
                try:
                    if x is None or (isinstance(x, float) and pd.isna(x)):
                        return ""
                    return f"{int(round(float(x)))}"
                except Exception:
                    return x

            fmt = {}
            for c in ["power","level","rail_gun","armor","data_chip","radar",
                      "weapon_level","max_skill_level","skill1","skill2","skill3"]:
                if c in df_show.columns:
                    fmt[c] = fmt_int

            try:
                styled = df_show.style.apply(lambda _df: style_cells(df_show), axis=None).format(fmt)
                st.dataframe(styled, use_container_width=True)
            except Exception:
                st.dataframe(df_show, use_container_width=True)

    except Exception as e:
        st.error("Could not load heroes (check table name/columns).")
        st.code(str(e))

# ============================
# Add or Update Heros page
# ============================
elif page == "Add or Update Hero":
    st.header("Add or Update Hero")

    # Load existing heroes for selector (sorted by power desc)
    try:
        sel_cols = "id,name,power"
        res = sb.table("heroes").select(sel_cols).order("power", desc=True).execute()
        hero_rows = res.data or []
    except Exception as e:
        st.error("Could not load heroes for selector.")
        st.code(str(e))
        hero_rows = []

    names = ["<Create new>"] + [h.get("name", "") for h in hero_rows]
    selected = st.selectbox("Choose hero", names, index=0)

    # If editing, fetch full row
    current = None
    if selected != "<Create new>":
        cur = next((h for h in hero_rows if h.get("name") == selected), None)
        if cur and cur.get("id"):
            try:
                full = sb.table("heroes").select(
                    "id,name,level,power,"
                    "rail_gun,rail_gun_stars,armor,armor_stars,data_chip,data_chip_stars,radar,radar_stars,"
                    "weapon,weapon_level,max_skill_level,skill1,skill2,skill3,"
                    "type,role,team,updated_at"
                ).eq("id", cur["id"]).maybe_single().execute().data
                current = full or cur
            except Exception:
                current = cur

    def v(d, k, default=None):
        return (d.get(k) if d else default)

    colA, colB, colC = st.columns(3)

    with colA:
        name = st.text_input("Name *", value=v(current, "name", "") or "")
        type_ = st.text_input("Type", value=v(current, "type", "") or "")
        role = st.selectbox("Role", ["", "Attack", "Defense", "Support"], index=0 if not v(current, "role") else
                            ["", "Attack", "Defense", "Support"].index(str(v(current, "role"))) if str(v(current, "role")) in ["", "Attack", "Defense", "Support"] else 0)
        team = st.text_input("Team", value=v(current, "team", "") or "")

    with colB:
        level = st.number_input("Level", min_value=0, max_value=200, value=int(v(current, "level", 0) or 0), step=1)

        # power is numeric/decimal in DB; allow float entry
        p_in = v(current, "power", 0)
        try:
            p_val = float(p_in) if p_in is not None else 0.0
        except Exception:
            p_val = 0.0
        power = st.number_input("Power", min_value=0.0, step=1.0, value=float(p_val))

        weapon = st.checkbox("Weapon?", value=bool(v(current, "weapon", False)))
        weapon_level = st.number_input("Weapon Level", min_value=0, max_value=200, value=int(v(current, "weapon_level", 0) or 0), step=1)
        max_skill_level = st.number_input("Max Skill Level", min_value=0, max_value=40, value=int(v(current, "max_skill_level", 0) or 0), step=1)

    with colC:
        rail_gun = st.number_input("Rail Gun", min_value=0, max_value=200, value=int(v(current, "rail_gun", 0) or 0), step=1)
        rail_gun_stars = st.text_input("Rail Gun Stars", value=v(current, "rail_gun_stars", "") or "")
        armor = st.number_input("Armor", min_value=0, max_value=200, value=int(v(current, "armor", 0) or 0), step=1)
        armor_stars = st.text_input("Armor Stars", value=v(current, "armor_stars", "") or "")
        data_chip = st.number_input("Data Chip", min_value=0, max_value=200, value=int(v(current, "data_chip", 0) or 0), step=1)
        data_chip_stars = st.text_input("Data Chip Stars", value=v(current, "data_chip_stars", "") or "")
        radar = st.number_input("Radar", min_value=0, max_value=200, value=int(v(current, "radar", 0) or 0), step=1)
        radar_stars = st.text_input("Radar Stars", value=v(current, "radar_stars", "") or "")

    st.divider()

    # Validate and actions
    errors = []
    if not name.strip():
        errors.append("Name is required.")

    if errors:
        for e in errors:
            st.error(e)
    else:
        col_save, col_delete = st.columns([1,1])

    # Save / Reload buttons for levels (KV)
    colA, colB = st.columns(2)

    with colA:
        if st.button("Save changes", use_container_width=True):
            try:
                # we only need name + level to save
                to_save = edited[["name", "level"]].copy()

                changes = []
                for _, r in to_save.iterrows():
                    key = r["name"]
                    lvl = int(r.get("level", 0) or 0)
                    # compare to current_map (string compare is fine since KV stores text)
                    if str(current_map.get(key, "")) != str(lvl):
                        changes.append({"key": key, "value": str(lvl)})

                if changes:
                    sb.table("buildings_kv").upsert(changes).execute()

                st.success("Saved")
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")

    with colB:
        if st.button("Reload from Supabase", use_container_width=True):
            st.rerun()


# ============================
# Research helpers (top-level)
# ============================

RESEARCH_CATEGORIES = [
    "Development",
    "Economy",
    "Hero",
    "Units",
    "Squad 1",
    "Squad 2",
    "Squad 3",
    "Squad 4",
    "Alliance Duel",
    "Intercity Truck",
    "Special Forces",
    "Siege to Seize",
    "Defense Fortifications",
    "Tank Mastery",
    "Missile Mastery",
    "Air Mastery",
    "The Age of Oil",
    "Tactical Weapon",
]

def research_load(category: str):
    import pandas as pd
    try:
        res = (
            sb.table("research_data")
              .select("id, name, level, max_level, order_index")
              .eq("category", category)
              .order("order_index")
              .execute()
        )
        rows = res.data or []
    except Exception:
        rows = []
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["id","name","level","max_level","order_index"])
    for c in ["level","max_level","order_index"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    return df

def research_save(category: str, edited_df):
    payload = []
    for _, r in edited_df.iterrows():
        name = str(r.get("name", "")).strip()
        if not name:
            continue
        row = {
            "category": category,
            "name": name,
            "level": int(r.get("level", 0) or 0),
            "max_level": int(r.get("max_level", 0) or 0) or 10,
        }
        rid = r.get("id")
        if isinstance(rid, str) and rid:
            row["id"] = rid
        if "order_index" in edited_df.columns and pd.notna(r.get("order_index")):
            try:
                row["order_index"] = int(r.get("order_index"))
            except Exception:
                pass
        payload.append(row)
    if payload:
        sb.table("research_data").upsert(payload).execute()

def research_completion(df) -> float:
    import pandas as pd
    import numpy as np

    if df is None or df.empty:
        return 0.0

    levels = pd.to_numeric(df.get("level"), errors="coerce").fillna(0)
    maxes  = pd.to_numeric(df.get("max_level"), errors="coerce").fillna(0)

    # valid rows only (max_level > 0)
    valid = maxes > 0
    if not valid.any():
        return 0.0

    # clamp levels to max_level so row completion never exceeds 100%
    clamped = np.minimum(levels[valid], maxes[valid])
    frac = (clamped / maxes[valid]).fillna(0)

    return float(round(frac.mean() * 100, 1))

# ----- DB-backed tracking (🔥 tracked, ⭐ priority) -----
def tracking_load_sets(category: str) -> tuple[set, set]:
    try:
        res = (
            sb.table("research_tracking")
              .select("name, tracked, priority")
              .eq("category", category)
              .execute()
        )
        rows = res.data or []
        tracked = {r["name"] for r in rows if r.get("tracked")}
        starred = {r["name"] for r in rows if r.get("priority")}
        return tracked, starred
    except Exception:
        return set(), set()

def tracking_save_from_editor(category: str, edited_df):
    payload = []
    for _, r in edited_df.iterrows():
        name = str(r.get("name", "")).strip()
        if not name:
            continue
        payload.append({
            "category": category,
            "name": name,
            "tracked":  bool(r.get("track", False)),  # 🔥
            "priority": bool(r.get("star",  False)),  # ⭐
        })
    if payload:
        sb.table("research_tracking") \
            .upsert(payload, on_conflict="category,name") \
            .execute()


# ============================
# Research page
# ============================
if page == "Research":
    import pandas as pd

    st.header("Research")
    st.caption("Click a category to expand. Edit Level and Max Level. Use 🔥 for in-progress and ⭐ for next up.")

    for cat in RESEARCH_CATEGORIES:
        # Load rows and DB tracking sets
        df = research_load(cat)
        tracked_set, starred_set = tracking_load_sets(cat)

        # Inject local columns for editor view
        if "track" not in df.columns:
            df["track"] = df["name"].astype(str).isin(tracked_set)   # 🔥
        if "star" not in df.columns:
            df["star"]  = df["name"].astype(str).isin(starred_set)   # ⭐

        # Completion for title + status icons
        pct = research_completion(df)
        if pct >= 90:
            color_icon = "🟢"
        elif pct >= 50:
            color_icon = "🟠"
        else:
            color_icon = "🔴"

        extras = []
        if tracked_set: extras.append("🔥")
        if starred_set: extras.append("⭐")
        suffix = (" " + " ".join(extras)) if extras else ""

        label = f"{color_icon} {cat} — {pct:.1f}% complete{suffix}"

        with st.expander(label, expanded=False):
            st.markdown(f"**Tree Completion:** {pct:.1f}%")

            # Build editor: [track] [star] [name] [level] [max] [id]
            editor_cols = ["track","star","name","level","max_level","id"] if "id" in df.columns else ["track","star","name","level","max_level"]
            show = df[editor_cols].copy() if not df.empty else pd.DataFrame(columns=editor_cols)

            edited = st.data_editor(
                show,
                num_rows="dynamic",
                use_container_width=True,
                column_config={
                    "track": st.column_config.CheckboxColumn(""),
                    "star":  st.column_config.CheckboxColumn("⭐"),
                    "name":  st.column_config.TextColumn("Research Name", width="large", required=True),
                    "level": st.column_config.NumberColumn("Level", min_value=0, max_value=999, step=1),
                    "max_level": st.column_config.NumberColumn("Max Level", min_value=1, max_value=999, step=1),
                    "id":    st.column_config.Column("id", disabled=True, width="small") if "id" in show.columns else None,
                },
                hide_index=True,
                key=f"research_editor_{cat}",
            )

            # Persist tracking states so 🔥 and ⭐ survive refresh
            tracking_save_from_editor(cat, edited)

            # Right-aligned badges reflecting current grid state
            any_fire = bool(edited.get("track").any()) if "track" in edited.columns else False
            any_star = bool(edited.get("star").any())  if "star"  in edited.columns else False

            if any_fire or any_star:
                fire_html = '<div class="rw-badge">🔥<span>Researching</span></div>' if any_fire else ""
                star_html = '<div class="rw-badge dim">⭐<span>Next up</span></div>'   if any_star else ""

                badges_html = f"""
                <style>
                @keyframes pulse {{ 0%{{transform:scale(1)}} 50%{{transform:scale(1.07)}} 100%{{transform:scale(1)}} }}
                .rw-badges{{display:flex;justify-content:flex-end;margin-top:6px;gap:.5rem}}
                .rw-badge{{display:flex;align-items:center;gap:.35rem;font-weight:700;animation:pulse 1s infinite}}
                .rw-badge.dim{{opacity:.85}}
                </style>
                <div class="rw-badges">
                    {fire_html} {star_html}
                </div>
                """
                st.markdown(badges_html, unsafe_allow_html=True)

            # Actions + live completion preview
            colA, colB, colC = st.columns([1, 1, 6])
            with colA:
                if st.button("Save changes", key=f"save_{cat}", type="primary", use_container_width=True):
                    try:
                        to_save = edited.drop(columns=[c for c in ["track","star"] if c in edited.columns])
                        research_save(cat, to_save)
                        st.success("Saved")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Save failed: {e}")
            with colB:
                if st.button("Reload", key=f"reload_{cat}", use_container_width=True):
                    st.rerun()
            with colC:
                st.markdown(f"**Preview Completion:** {research_completion(edited):.1f}%")



# --------------------------------------------------
# Footer
# --------------------------------------------------
st.caption("Made with love. Drink a beer.")
