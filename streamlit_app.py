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

STAR_CHOICES = [
    "",
    "0.1","0.2","0.3","0.4",
    "1.0","1.1","1.2","1.3","1.4",
    "2.0","2.1","2.2","2.3","2.4",
    "3.0","3.1","3.2","3.3","3.4",
    "4.0","4.1","4.2","4.3","4.4",
    "5.0"
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
def df_from(data) -> pd.DataFrame:
    try:
        return pd.DataFrame(data)
    except Exception:
        return pd.DataFrame()

def load_catalog() -> pd.DataFrame:
    data = sb.table("hero_catalog").select("name,type,role").execute().data
    return df_from(data)

@st.cache_data(ttl=15)
def load_heroes() -> pd.DataFrame:
    data = sb.table("heroes").select("*").execute().data
    return df_from(data)

def get_hero_record(name: str) -> Dict[str, Any]:
    data = sb.table("heroes").select("*").eq("name", name).execute().data
    return data[0] if data else {}

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

# -------------------------------
# UI nav
# -------------------------------
page = st.sidebar.radio("Navigate", ["Heroes", "Add / Update Hero", "Dashboard (later)"])

# -------------------------------
# HEROES PAGE
# -------------------------------
if page == "Heroes":
    st.title("🧙 Heroes")

    cat = load_catalog()
    heroes = load_heroes()

    if heroes.empty and cat.empty:
        st.info("No heroes yet. Seed hero_catalog and add your first hero in 'Add / Update Hero'.")
    else:
        df = heroes.merge(cat, on="name", how="right", suffixes=("", "_cat"))
        if "type_cat" in df.columns:
            df["type"] = df["type"].fillna(df["type_cat"])
        if "role_cat" in df.columns:
            df["role"] = df["role"].fillna(df["role_cat"])

        c1, c2, c3 = st.columns(3)
        name_q = c1.text_input("Search Name")
        type_q = c2.text_input("Filter Type")
        role_q = c3.text_input("Filter Role")

        if name_q:
            df = df[df["name"].astype(str).str.contains(name_q, case=False, na=False)]
        if type_q:
            df = df[df["type"].astype(str).str.contains(type_q, case=False, na=False)]
        if role_q:
            df = df[df["role"].astype(str).str.contains(role_q, case=False, na=False)]

        if "power" in df.columns:
            df = df.sort_values(by=["power"], ascending=False, na_position="last")

        show_cols = [c for c in DISPLAY_COLUMNS if c in df.columns]
        st.dataframe(df[show_cols], use_container_width=True)

# -------------------------------
# ADD / UPDATE HERO
# -------------------------------
elif page == "Add / Update Hero":
    st.title("➕ Add / Update Hero")

    catalog = load_catalog()
    heroes = load_heroes()

    if catalog.empty:
        st.error("Catalog is empty. Seed hero_catalog first.")
    else:
        merged = catalog.merge(heroes[["name","power"]] if not heroes.empty else pd.DataFrame(columns=["name","power"]),
                               on="name", how="left")
        merged["power"] = merged["power"].fillna(0)
        merged = merged.sort_values("power", ascending=False)

        # Add blank option at top
        options = [""] + [f"{row['name']} (Power: {int(row['power'])})" for _, row in merged.iterrows()]
        selection = st.selectbox("Name", options, index=0)

        # No selection = empty state
        if selection == "":
            st.info("Select a hero from the dropdown to view or update their data.")
            st.stop()

        name = selection.split(" (Power")[0]
        row = merged[merged["name"] == name].iloc[0]
        st.caption(f"Type: **{row['type']}**  |  Role: **{row['role']}**  |  Power: **{int(row['power'])}**")

        # Get existing hero data
        hero_data = get_hero_record(name)

        with st.form("hero_full_update"):
            c1, c2 = st.columns(2)

            with c1:
                level = st.number_input("Level", min_value=0, max_value=200, step=1, value=hero_data.get("level", 0))
                power = st.number_input("Power", min_value=0, max_value=100_000_000, step=100, value=hero_data.get("power", 0))
                rail_gun = st.number_input("Rail Gun", min_value=0, max_value=999, step=1, value=hero_data.get("rail_gun", 0))
                rail_gun_stars = st.selectbox("Rail Gun Stars", STAR_CHOICES, index=STAR_CHOICES.index(str(hero_data.get("rail_gun_stars", ""))) if str(hero_data.get("rail_gun_stars", "")) in STAR_CHOICES else 0)
                armor = st.number_input("Armor", min_value=0, max_value=999, step=1, value=hero_data.get("armor", 0))
                armor_stars = st.selectbox("Armor Stars", STAR_CHOICES, index=STAR_CHOICES.index(str(hero_data.get("armor_stars", ""))) if str(hero_data.get("armor_stars", "")) in STAR_CHOICES else 0)
                data_chip = st.number_input("Data Chip", min_value=0, max_value=999, step=1, value=hero_data.get("data_chip", 0))
                data_chip_stars = st.selectbox("Data Chip Stars", STAR_CHOICES, index=STAR_CHOICES.index(str(hero_data.get("data_chip_stars", ""))) if str(hero_data.get("data_chip_stars", "")) in STAR_CHOICES else 0)

            with c2:
                radar = st.number_input("Radar", min_value=0, max_value=999, step=1, value=hero_data.get("radar", 0))
                radar_stars = st.selectbox("Radar Stars", STAR_CHOICES, index=STAR_CHOICES.index(str(hero_data.get("radar_stars", ""))) if str(hero_data.get("radar_stars", "")) in STAR_CHOICES else 0)
                weapon = st.selectbox("Weapon", ["Yes", "No"], index=0 if hero_data.get("weapon", False) else 1)
                weapon_level = st.number_input("Weapon Level", min_value=0, max_value=999, step=1, value=hero_data.get("weapon_level", 0))
                max_skill_level = st.number_input("Max Skill Level", min_value=0, max_value=999, step=1, value=hero_data.get("max_skill_level", 0))
                skill1 = st.number_input("Skill 1", min_value=0, max_value=999, step=1, value=hero_data.get("skill1", 0))
                skill2 = st.number_input("Skill 2", min_value=0, max_value=999, step=1, value=hero_data.get("skill2", 0))
                skill3 = st.number_input("Skill 3", min_value=0, max_value=999, step=1, value=hero_data.get("skill3", 0))

            submitted = st.form_submit_button("Save")

        if submitted:
            fields = {
                "level": int(level),
                "power": int(power),
                "rail_gun": int(rail_gun),
                "rail_gun_stars": rail_gun_stars or None,
                "armor": int(armor),
                "armor_stars": armor_stars or None,
                "data_chip": int(data_chip),
                "data_chip_stars": data_chip_stars or None,
                "radar": int(radar),
                "radar_stars": radar_stars or None,
                "weapon": True if weapon == "Yes" else False,
                "weapon_level": int(weapon_level),
                "max_skill_level": int(max_skill_level),
                "skill1": int(skill1),
                "skill2": int(skill2),
                "skill3": int(skill3),
            }

            try:
                upsert_hero_by_name(name, fields)
                st.success(f"Saved all data for {name}")
                st.cache_data.clear()
            except Exception as e:
                st.error(f"Failed to save: {e}")

# -------------------------------
# DASHBOARD (placeholder)
# -------------------------------
else:
    st.title("📊 Dashboard (coming soon)")
    st.info("We’ll add charts and summaries here once data is flowing.")
