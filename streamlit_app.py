import streamlit as st
import pandas as pd
from typing import Dict, Any
from supabase import create_client, Client

st.set_page_config(page_title="Last War Heroes", page_icon="🎮", layout="wide")

# -------------------------------------------------
# Supabase connection
# -------------------------------------------------
@st.cache_resource
def get_supabase() -> Client:
    return create_client(st.secrets["supabase_url"], st.secrets["supabase_key"])

sb = get_supabase()

STAR_CHOICES = [
    "",
    "0.1","0.2","0.3","0.4",
    "1.0","1.1","1.2","1.3","1.4",
    "2.0","2.1","2.2","2.3","2.4",
    "3.0","3.1","3.2","3.3","3.4",
    "4.0","4.1","4.2","4.3","4.4",
]

NUMERIC_FIELDS = [
    "level","power","rail_gun","armor","data_chip","radar",
    "weapon_level","max_skill_level","skill1","skill2","skill3"
]

DISPLAY_COLUMNS = [
    "name","type","role","level","power",
    "rail_gun","rail_gun_stars","armor","armor_stars",
    "data_chip","data_chip_stars","radar","radar_stars",
    "weapon","weapon_level","max_skill_level","skill1","skill2","skill3",
]

# -------------------------------------------------
# Utility functions
# -------------------------------------------------
def load_catalog() -> pd.DataFrame:
    data = sb.table("hero_catalog").select("name,type,role").order("name").execute().data
    return pd.DataFrame(data)

@st.cache_data(ttl=15)
def load_heroes() -> pd.DataFrame:
    data = sb.table("heroes").select("*").execute().data
    return pd.DataFrame(data)

def upsert_hero_by_name(name: str, fields: Dict[str, Any]):
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

# -------------------------------------------------
# Page navigation
# -------------------------------------------------
page = st.sidebar.radio("Navigate", ["Heroes", "Add / Update Hero", "Dashboard (later)"])

# -------------------------------------------------
# HEROES PAGE
# -------------------------------------------------
if page == "Heroes":
    st.title("🧙 Heroes")

    cat = load_catalog()
    df = load_heroes()
    if not df.empty:
        out = df.merge(cat, on="name", how="left", suffixes=("", "_cat"))
        out["type"] = out["type"].fillna(out.get("type_cat"))
        out["role"] = out["role"].fillna(out.get("role_cat"))
    else:
        out = pd.DataFrame(columns=DISPLAY_COLUMNS)

    name_q = st.text_input("Search Name")
    type_q = st.text_input("Filter Type")
    role_q = st.text_input("Filter Role")

    if not out.empty:
        if name_q:
            out = out[out["name"].astype(str).str.contains(name_q, case=False, na=False)]
        if type_q:
            out = out[out["type"].astype(str).str.contains(type_q, case=False, na=False)]
        if role_q:
            out = out[out["role"].astype(str).str.contains(role_q, case=False, na=False)]
        show_cols = [c for c in DISPLAY_COLUMNS if c in out.columns]
        st.dataframe(out[show_cols].sort_values(by=["power"], ascending=False), use_container_width=True)
    else:
        st.info("No heroes yet. Add one in 'Add / Update Hero'.")

# -------------------------------------------------
# ADD / UPDATE HERO PAGE
# -------------------------------------------------
elif page == "Add / Update Hero":
    st.title("➕ Add / Update Hero")

    catalog = load_catalog()
    if catalog.empty:
        st.error("Catalog is empty. Seed hero_catalog first.")
    else:
        names = catalog["name"].tolist()
        name = st.selectbox("Name", names)
        row = catalog[catalog["name"] == name].iloc[0]
        st.caption(f"Type: **{row['type']}**  |  Role: **{row['role']}**")
        st.write("Choose only the fields you want to update. Leave others blank.")

        with st.form("hero_form"):
            c1, c2 = st.columns(2)
            with c1:
                level = st.number_input("Level", min_value=0, max_value=200, step=1)
                power = st.number_input("Power", min_value=0, max_value=100_000_000, step=100)
                rail_gun = st.number_input("Rail Gun", min_value=0, max_value=999)
                rail_gun_stars = st.selectbox("Rail Gun Stars", STAR_CHOICES)
                armor = st.number_input("Armor", min_value=0, max_value=999)
                armor_stars = st.selectbox("Armor Stars", STAR_CHOICES)
                data_chip = st.number_input("Data Chip", min_value=0, max_value=999)
                data_chip_stars = st.selectbox("Data Chip Stars", STAR_CHOICES)
            with c2:
                radar = st.number_input("Radar", min_value=0, max_value=999)
                radar_stars = st.selectbox("Radar Stars", STAR_CHOICES)
                weapon = st.selectbox("Weapon", ["Leave unchanged", "Yes", "No"])
                weapon_level = st.number_input("Weapon Level", min_value=0, max_value=999)
                max_skill_level = st.number_input("Max Skill Level", min_value=0, max_value=999)
                skill1 = st.number_input("Skill 1", min_value=0, max_value=999)
                skill2 = st.number_input("Skill 2", min_value=0, max_value=999)
                skill3 = st.number_input("Skill 3", min_value=0, max_value=999)
            submitted = st.form_submit_button("Save")

        if submitted:
            fields = {
                "level": int(level) if level else None,
                "power": int(power) if power else None,
                "rail_gun": int(rail_gun) if rail_gun else None,
                "rail_gun_stars": rail_gun_stars or None,
                "armor": int(armor) if armor else None,
                "armor_stars": armor_stars or None,
                "data_chip": int(data_chip) if data_chip else None,
                "data_chip_stars": data_chip_stars or None,
                "radar": int(radar) if radar else None,
                "radar_stars": radar_stars or None,
                "weapon_level": int(weapon_level) if weapon_level else None,
                "max_skill_level": int(max_skill_level) if max_skill_level else None,
                "skill1": int(skill1) if skill1 else None,
                "skill2": int(skill2) if skill2 else None,
                "skill3": int(skill3) if skill3 else None,
            }
            if weapon != "Leave unchanged":
                fields["weapon"] = True if weapon == "Yes" else False
            clean = {k: v for k, v in fields.items() if v not in (None, "", 0)}
            try:
                upsert_hero_by_name(name, clean)
                st.success(f"Saved changes for {name}")
                st.cache_data.clear()
            except Exception as e:
                st.error(f"Error saving hero: {e}")

# -------------------------------------------------
# DASHBOARD PLACEHOLDER
# -------------------------------------------------
else:
    st.title("📊 Dashboard (coming soon)")
    st.info("We’ll add charts and summaries here once data is flowing.")
