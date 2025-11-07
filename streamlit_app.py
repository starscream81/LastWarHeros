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

    def team_row(i: int):
        # narrow select, narrow power, big spacer to keep everything left
        sel_col, pow_col, _spacer = st.columns([1.2, 0.9, 10])
        with sel_col:
            st.selectbox(
                f"Team {i}",
                team_opts,
                index=0,
                key=f"team_{i}_type",
                label_visibility="visible",
            )
        with pow_col:
            st.text_input(
                "Power",
                key=f"team_{i}_power",
                max_chars=6,             # e.g., 32.46M
                placeholder="32.46M",
                label_visibility="visible",
            )

    for i in range(1, 4):
        team_row(i)


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



elif page == "Buildings":
    st.header("Buildings")
    st.write("Standard table. Only updates rows you actually change. No undo/redo.")
    # Load current values
    current = kv_bulk_read(DEFAULT_BUILDINGS)
    buildings_table(current)

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

        with col_save:
            if st.button("Save / Upsert", type="primary", use_container_width=True):
                try:
                    payload = {
                        "name": name.strip(),
                        "type": type_.strip(),
                        "role": role.strip(),
                        "team": team.strip(),
                        "level": int(level),
                        "power": float(power),
                        "weapon": bool(weapon),
                        "weapon_level": int(weapon_level),
                        "max_skill_level": int(max_skill_level),
                        "rail_gun": int(rail_gun),
                        "rail_gun_stars": rail_gun_stars.strip(),
                        "armor": int(armor),
                        "armor_stars": armor_stars.strip(),
                        "data_chip": int(data_chip),
                        "data_chip_stars": data_chip_stars.strip(),
                        "radar": int(radar),
                        "radar_stars": radar_stars.strip(),
                    }
                    if current and current.get("id"):
                        payload["id"] = current["id"]  # retain id to update the same row

                    sb.table("heroes").upsert(payload).execute()
                    st.success("Saved.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Save failed: {e}")

        with col_delete:
            if current and current.get("id"):
                if st.button("Delete hero", use_container_width=True):
                    try:
                        sb.table("heroes").delete().eq("id", current["id"]).execute()
                        st.success("Deleted.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Delete failed: {e}")

# ============================
# Research: helpers + page
# ============================

# ---- Categories shown in the page sidebar/expanders
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
    "Tank Mastery",
    "Missile Mastery",
    "Air Mastery",
    "The Age of Oil",
    "Tactical Weapon",
]

# ---- Loader: read a category from Supabase in stable order
def research_load(category: str):
    import pandas as pd
    try:
        res = (
            sb.table("research_data")
              .select("id, name, level, max_level, order_index")
              .eq("category", category)
              .order("order_index")         # preserves your custom order
              .execute()
        )
        rows = res.data or []
    except Exception:
        rows = []

    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["id", "name", "level", "max_level", "order_index"])

    # type safety
    for c in ["level", "max_level", "order_index"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    return df

# ---- Saver: upsert edited rows for a category
def research_save(category: str, edited_df):
    payload = []
    keep_cols = {"category", "id", "name", "level", "max_level", "order_index"}
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
        # keep existing id/order_index if present
        if isinstance(r.get("id"), str) and r.get("id"):
            row["id"] = r["id"]
        if "order_index" in edited_df.columns and pd.notna(r.get("order_index")):
            try:
                row["order_index"] = int(r.get("order_index"))
            except Exception:
                pass
        payload.append({k: v for k, v in row.items() if k in keep_cols})

    if payload:
        sb.table("research_data").upsert(payload).execute()

# ---- Completion % for a DataFrame (average of level / max_level)
def research_completion(df) -> float:
    import pandas as pd
    if df is None or df.empty:
        return 0.0
    levels = pd.to_numeric(df.get("level"), errors="coerce").fillna(0)
    maxes  = pd.to_numeric(df.get("max_level"), errors="coerce").replace(0, pd.NA)
    frac = (levels / maxes).fillna(0)
    return float(round(frac.mean() * 100, 1)) if len(frac) else 0.0

# ---- Session-only tracking (checkbox) — does NOT touch DB
TRACK_STATE_KEY = "research_tracking"  # {category: set([names])}

def _get_tracked_set(category: str) -> set:
    st.session_state.setdefault(TRACK_STATE_KEY, {})
    st.session_state[TRACK_STATE_KEY].setdefault(category, set())
    return st.session_state[TRACK_STATE_KEY][category]

def _update_tracked_from_df(category: str, df_with_track):
    tracked = {str(r["name"]) for _, r in df_with_track.iterrows() if r.get("track", False)}
    st.session_state[TRACK_STATE_KEY][category] = tracked


# ============================
# Research page
# ============================
elif page == "Research":
    import pandas as pd
    st.header("Research")
    st.caption("Click a category to expand. Add rows if needed. Edit Level or Max Level, then Save changes.")

    for cat in RESEARCH_CATEGORIES:
        # Load rows for this category
        df = research_load(cat)

        # Session-only "track" column (checkboxes)
        tracked_set = _get_tracked_set(cat)
        if "track" not in df.columns:
            df["track"] = df["name"].astype(str).isin(tracked_set)

        # Completion for title
        pct = research_completion(df)
        if pct >= 90:
            icon = "🟢"
        elif pct >= 50:
            icon = "🟠"
        else:
            icon = "🔴"

        # Show 🔥 in the title if anything in this category is currently tracked
        fire_title = " 🔥" if len(tracked_set) > 0 else ""
        label = f"{icon} {cat} — {pct:.1f}% complete{fire_title}"

        with st.expander(label, expanded=False):  # all start collapsed
            # Optional summary inside
            st.markdown(f"**Tree Completion:** {pct:.1f}%")

            # Build the editor view: checkbox first
            editor_cols = ["track", "name", "level", "max_level", "id"] if "id" in df.columns else ["track", "name", "level", "max_level"]
            show = df[editor_cols].copy() if not df.empty else pd.DataFrame(columns=editor_cols)

            edited = st.data_editor(
                show,
                num_rows="dynamic",                # allow adding new lines
                use_container_width=True,
                column_config={
                    "track": st.column_config.CheckboxColumn(""),
                    "name": st.column_config.TextColumn("Research Name", width="large", required=True),
                    "level": st.column_config.NumberColumn("Level", min_value=0, max_value=999, step=1),
                    "max_level": st.column_config.NumberColumn("Max Level", min_value=1, max_value=999, step=1),
                    "id": st.column_config.Column("id", disabled=True, width="small") if "id" in show.columns else None,
                },
                hide_index=True,
                key=f"research_editor_{cat}",
            )

            # Update local tracking after edits (no DB write)
            _update_tracked_from_df(cat, edited)

            # Right-aligned animated "Researching" badge if anything is tracked
            any_tracked_now = bool(edited["track"].any()) if "track" in edited.columns else False
            if any_tracked_now:
                st.markdown(
                    """
                    <style>
                    @keyframes flamePulse {
                      0%   { transform: scale(1);   filter: drop-shadow(0 0 0 rgba(255,120,0,0.2)); }
                      50%  { transform: scale(1.07); filter: drop-shadow(0 0 8px rgba(255,140,0,0.75)); }
                      100% { transform: scale(1);   filter: drop-shadow(0 0 0 rgba(255,120,0,0.2)); }
                    }
                    .rw-badge { display:flex; justify-content:flex-end; margin-top:6px; }
                    .rw-fire  { animation: flamePulse 1s infinite; margin-right:6px; }
                    .rw-text  { font-weight:700; }
                    </style>
                    <div class="rw-badge">
                      <div class="rw-fire">🔥</div>
                      <div class="rw-text">Researching</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            # Actions row + live preview completion
            colA, colB, colC = st.columns([1, 1, 6])
            with colA:
                if st.button("Save changes", key=f"save_{cat}", type="primary", use_container_width=True):
                    try:
                        # Exclude the local-only 'track' column before saving
                        to_save = edited.drop(columns=[c for c in ["track"] if c in edited.columns])
                        research_save(cat, to_save)
                        st.success("Saved")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Save failed: {e}")
            with colB:
                if st.button("Reload", key=f"reload_{cat}", use_container_width=True):
                    st.rerun()
            with colC:
                preview_pct = research_completion(edited.rename(columns={"track": "level"}) if "track" not in edited.columns else edited.assign(level=edited["level"]))
                st.markdown(f"**Preview Completion:** {research_completion(edited):.1f}%")


# --------------------------------------------------
# Footer
# --------------------------------------------------
st.caption("Made with love. Drink a beer.")
