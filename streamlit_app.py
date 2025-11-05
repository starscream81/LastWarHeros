import streamlit as st
import pandas as pd
from typing import Dict, Any
from supabase import create_client, Client

# -------------------------------
# App setup
# -------------------------------
st.set_page_config(page_title="Last War Heroes", page_icon="🎮", layout="wide")

@st.cache_resource
def get_supabase() -> Client:
    return create_client(st.secrets["supabase_url"], st.secrets["supabase_key"])

sb = get_supabase()

# Stars list with 5.0 added
STAR_CHOICES = [
    "",
    "0.1","0.2","0.3","0.4",
    "1.0","1.1","1.2","1.3","1.4",
    "2.0","2.1","2.2","2.3","2.4",
    "3.0","3.1","3.2","3.3","3.4",
    "4.0","4.1","4.2","4.3","4.4",
    "5.0",
]

DISPLAY_COLUMNS = [
    "name","type","role","level","power",
    "rail_gun","rail_gun_stars","armor","armor_stars",
    "data_chip","data_chip_stars","radar","radar_stars",
    "weapon","weapon_level","max_skill_level","skill1","skill2","skill3",
]

# -------------------------------
# Data helpers
# -------------------------------
def _df_from_query(data) -> pd.DataFrame:
    try:
        return pd.DataFrame(data)
    except Exception:
        return pd.DataFrame()

def load_catalog() -> pd.DataFrame:
    # name, type, role live here
    data = sb.table("hero_catalog").select("name,type,role").execute().data
    return _df_from_query(data)

@st.cache_data(ttl=15)
def load_heroes() -> pd.DataFrame:
    # editable stats live here
    data = sb.table("heroes").select("*").execute().data
    return _df_from_query(data)

def upsert_hero_by_name(name: str, fields: Dict[str, Any]):
    """Insert if missing; otherwise partial update by name. Also backfill type/role from catalog."""
    catalog = load_catalog()
    match = catalog[catalog["name"] == name]
    if not match.empty:
        fields.setdefault("type", match.iloc[0]["type"])
        fields.setdefault("role", match.iloc[0]["role"])

    existing = sb.table("heroes").select("id").eq("name", name).execute().data
    if existing:
        sb.table("heroes").update(fields).eq("id", existing[0]["id"]).execute()
    else:
        sb.table("heroes").insert({"name": name, **fields}).execute()

# -------------------------------
# UI nav
# -------------------------------
page = st.sidebar.radio("Navigate", ["Heroes", "Add / Update Hero", "Dashboard (later)"])

# -------------------------------
# HEROES (list)
# -------------------------------
if page == "Heroes":
    st.title("🧙 Heroes")

    cat = load_catalog()
    heroes = load_heroes()

    if heroes.empty and cat.empty:
        st.info("No heroes yet. Seed hero_catalog and add your first hero in 'Add / Update Hero'.")
    else:
        # merge to ensure Type/Role visible even if not in heroes table yet
        df = heroes.merge(cat, on="name", how="right", suffixes=("", "_cat"))
        if "type" in df.columns and "type_cat" in df.columns:
            df["type"] = df["type"].fillna(df["type_cat"])
        if "role" in df.columns and "role_cat" in df.columns:
            df["role"] = df["role"].fillna(df["role_cat"])

        # Filters
        c1, c2, c3 = st.columns(3)
        with c1:
            name_q = st.text_input("Search Name")
        with c2:
            type_q = st.text_input("Filter Type")
        with c3:
            role_q = st.text_input("Filter Role")

        if name_q:
            df = df[df["name"].astype(str).str.contains(name_q, case=False, na=False)]
        if type_q and "type" in df:
            df = df[df["type"].astype(str).str.contains(type_q, case=False, na=False)]
        if role_q and "role" in df:
            df = df[df["role"].astype(str).str.contains(role_q, case=False, na=False)]

        # Sort by power desc if available
        if "power" in df.columns:
            df = df.sort_values(by=["power"], ascending=False, na_position="last")

        show_cols = [c for c in DISPLAY_COLUMNS if c in df.columns]
        if not show_cols:
            show_cols = ["name","type","role"]
        st.dataframe(df[show_cols], use_container_width=True)

# -------------------------------
# ADD / UPDATE HERO (partial updates)
# -------------------------------
elif page == "Add / Update Hero":
    st.title("➕ Add / Update Hero")

    catalog = load_catalog()
    heroes = load_heroes()

    if catalog.empty:
        st.error("Catalog is empty. Seed hero_catalog first.")
    else:
        # Merge catalog + heroes so we can sort by current power
        merged = catalog.merge(heroes[["name","power"]] if not heroes.empty else pd.DataFrame(columns=["name","power"]),
                               on="name", how="left")
        merged["power"] = merged["power"].fillna(0)
        merged = merged.sort_values("power", ascending=False)

        # Dropdown options like: "Kimberly (Power: 38400000)"
        options = [f"{row['name']} (Power: {int(row['power'])})" for _, row in merged.iterrows()]
        if not options:
            st.warning("No names found in catalog.")
            st.stop()

        selection = st.selectbox("Name", options)
        name = selection.split(" (Power")[0]
        row = merged[merged["name"] == name].iloc[0]
        st.caption(f"Type: **{row['type']}**  |  Role: **{row['role']}**  |  Power: **{int(row['power'])}**")

        st.write("Check a box to update that field. Leave unchecked to keep the existing value.")

        with st.form("hero_partial_update"):
            def num_field(label: str, key: str, min_v=0, max_v=100_000_000, step=1, default=0):
                en = st.checkbox(f"Update {label}", key=f"en_{key}")
                val = None
                if en:
                    val = st.number_input(label, min_value=min_v, max_value=max_v, value=default, step=step, key=f"val_{key}")
                return en, val

            def star_field(label: str, key: str):
                en = st.checkbox(f"Update {label}", key=f"en_{key}")
                val = None
                if en:
                    val = st.selectbox(label, STAR_CHOICES, index=0, key=f"val_{key}")
                    if val == "":
                        val = None
                return en, val

            c1, c2 = st.columns(2)

            with c1:
                en_lvl, level = num_field("Level", "level", min_v=0, max_v=200, step=1, default=0)
                en_pow, power = num_field("Power", "power", min_v=0, max_v=100_000_000, step=100, default=int(row["power"]) if "power" in row else 0)
                en_rg, rail_gun = num_field("Rail Gun", "railgun", min_v=0, max_v=999, step=1)
                en_rg_s, rail_gun_stars = star_field("Rail Gun Stars", "rgstars")
                en_arm, armor = num_field("Armor", "armor", min_v=0, max_v=999, step=1)
                en_arm_s, armor_stars = star_field("Armor Stars", "armorstars")
                en_chip, data_chip = num_field("Data Chip", "datachip", min_v=0, max_v=999, step=1)
                en_chip_s, data_chip_stars = star_field("Data Chip Stars", "chipstars")

            with c2:
                en_rad, radar = num_field("Radar", "radar", min_v=0, max_v=999, step=1)
                en_rad_s, radar_stars = star_field("Radar Stars", "radarstars")

                weapon_mode = st.selectbox("Weapon", ["Leave unchanged", "Yes", "No"], index=0)
                en_wlvl, weapon_level = num_field("Weapon Level", "weaponlvl", min_v=0, max_v=999, step=1)
                en_msl, max_skill_level = num_field("Max Skill Level", "maxskill", min_v=0, max_v=999, step=1)
                en_s1, skill1 = num_field("Skill 1", "skill1", min_v=0, max_v=999, step=1)
                en_s2, skill2 = num_field("Skill 2", "skill2", min_v=0, max_v=999, step=1)
                en_s3, skill3 = num_field("Skill 3", "skill3", min_v=0, max_v=999, step=1)

            submitted = st.form_submit_button("Save")

        if submitted:
            fields: Dict[str, Any] = {}
            if en_lvl: fields["level"] = int(level)
            if en_pow: fields["power"] = int(power)
            if en_rg: fields["rail_gun"] = int(rail_gun)
            if en_rg_s: fields["rail_gun_stars"] = rail_gun_stars
            if en_arm: fields["armor"] = int(armor)
            if en_arm_s: fields["armor_stars"] = armor_stars
            if en_chip: fields["data_chip"] = int(data_chip)
            if en_chip_s: fields["data_chip_stars"] = data_chip_stars
            if en_rad: fields["radar"] = int(radar)
            if en_rad_s: fields["radar_stars"] = radar_stars
            if weapon_mode != "Leave unchanged":
                fields["weapon"] = True if weapon_mode == "Yes" else False
            if en_wlvl: fields["weapon_level"] = int(weapon_level)
            if en_msl: fields["max_skill_level"] = int(max_skill_level)
            if en_s1: fields["skill1"] = int(skill1)
            if en_s2: fields["skill2"] = int(skill2)
            if en_s3: fields["skill3"] = int(skill3)

            try:
                upsert_hero_by_name(name, fields)
                st.success(f"Saved changes for {name}")
                st.cache_data.clear()
            except Exception as e:
                st.error(f"Failed to save: {e}")

# -------------------------------
# DASHBOARD (placeholder)
# -------------------------------
else:
    st.title("📊 Dashboard (coming soon)")
    st.info("We’ll add charts and summaries here once data is flowing.")
