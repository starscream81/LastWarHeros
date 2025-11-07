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
_conn_ok = True
try:
    sb.table("buildings_kv").select("key").limit(1).execute()
except Exception:
    _conn_ok = False
st.info("Connected to Supabase" if _conn_ok else "Cannot reach Supabase — check URL/key and RLS.")

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
PAGES = ["Dashboard", "Buildings", "Heroes", "Add or Update Hero"]
with st.sidebar:
    st.title("LastWarHeros")
    page = st.radio("Navigate", PAGES, index=1)  # land on Buildings first while we build

# --------------------------------------------------
# Pages
# --------------------------------------------------
if page == "Dashboard":
    st.header("Dashboard")
    st.info("We'll wire this after we lock the other pages.")

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
    st.info("Once you confirm the Heroes table schema, we will build this form to match and persist to Supabase.")

# --------------------------------------------------
# Footer
# --------------------------------------------------
st.caption("Source of truth: Supabase buildings_kv. This page uses a table with explicit 'Save changes' to avoid accidental writes.")
