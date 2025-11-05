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

# Helper to title-case headers and remove underscores
def pretty_col(col: str) -> str:
    return col.replace("_"," ").title()

PRETTY_COLUMNS_MAP = {c: pretty_col(c) for c in DISPLAY_COLUMNS}

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
if "nav" not in st.session_state:
    st.session_state["nav"] = "Heroes"

page = st.sidebar.radio("Navigate", ["Heroes", "Add / Update Hero", "Dashboard (later)"], key="nav")

# -------------------------------
# HEROES PAGE (styled inline)
# -------------------------------
if page == "Heroes":
    st.title("🧙 Heroes")

    cat = load_catalog()
    heroes = load_heroes()

    if heroes.empty and cat.empty:
        st.info("No heroes yet. Seed hero_catalog and add your first hero in 'Add / Update Hero'.")
    else:
        # Merge to ensure Type/Role always present
        df = heroes.merge(cat, on="name", how="right", suffixes=("", "_cat"))
        if "type_cat" in df.columns:
            df["type"] = df["type"].fillna(df["type_cat"])
        if "role_cat" in df.columns:
            df["role"] = df["role"].fillna(df["role_cat"])

        # Sort by power desc (if present)
        if "power" in df.columns:
            df = df.sort_values(by=["power"], ascending=False, na_position="last")

        # Prepare display copy: blank out None, weapon only "Yes"
        disp = df.copy()

        # Weapon display rule: only show "Yes", otherwise blank
        if "weapon" in disp.columns:
            disp["weapon"] = disp["weapon"].apply(lambda x: "Yes" if x is True else "")

        # Replace NaN/None with blanks for every column
        disp = disp.replace({None: ""})
        disp = disp.fillna("")

        # Select columns to display and rename headers
        show_cols = [c for c in DISPLAY_COLUMNS if c in disp.columns]
        disp = disp[show_cols]
        disp = disp.rename(columns=PRETTY_COLUMNS_MAP)

        # Build masks for styling on the original df (use original column names)
        # Map pretty column names back to original for styling function
        inv_pretty = {v: k for k, v in PRETTY_COLUMNS_MAP.items()}

        # Styling function
        orange = "background-color: #FFA50033;"  # light orange
        green  = "background-color: #2ECC7133;"  # light green

        def style_rows(styler_df_display: pd.DataFrame):
            # Convert display df columns back to originals for logic
            # We'll create a parallel "logic df" using the same row order
            logic_df = df.reset_index(drop=True)
            styles = pd.DataFrame("", index=styler_df_display.index, columns=styler_df_display.columns)

            # Column name helpers (display names)
            col_rg   = PRETTY_COLUMNS_MAP["rail_gun"]
            col_rgs  = PRETTY_COLUMNS_MAP["rail_gun_stars"]
            col_arm  = PRETTY_COLUMNS_MAP["armor"]
            col_arms = PRETTY_COLUMNS_MAP["armor_stars"]
            col_chip = PRETTY_COLUMNS_MAP["data_chip"]
            col_chps = PRETTY_COLUMNS_MAP["data_chip_stars"]
            col_rad  = PRETTY_COLUMNS_MAP["radar"]
            col_rads = PRETTY_COLUMNS_MAP["radar_stars"]
            col_role = PRETTY_COLUMNS_MAP["role"]

            # Iterate rows
            for i in styler_df_display.index:
                # Safe getters
                role = str(logic_df.at[i, "role"]) if "role" in logic_df.columns else ""

                # Green overrides
                def green_pair(num_col_display, star_col_display, num_col_logic, star_col_logic):
                    try:
                        num_ok  = pd.to_numeric(logic_df.at[i, num_col_logic]) == 40
                    except Exception:
                        num_ok = False
                    star_ok = str(logic_df.at[i, star_col_logic]) == "5.0"
                    if num_ok and star_ok:
                        styles.at[i, num_col_display] = green
                        styles.at[i, star_col_display] = green
                        return True
                    return False

                # Apply green first (overrides)
                _rg_green  = green_pair(col_rg,  col_rgs,  "rail_gun",   "rail_gun_stars")
                _ar_green  = green_pair(col_arm, col_arms, "armor",      "armor_stars")
                _dc_green  = green_pair(col_chip,col_chps, "data_chip",  "data_chip_stars")
                _ra_green  = green_pair(col_rad, col_rads, "radar",      "radar_stars")

                # Orange by role (only if not green on each pair)
                if role.lower() == "attack":
                    if not _rg_green:
                        styles.at[i, col_rg]  = orange
                        styles.at[i, col_rgs] = orange
                    if not _dc_green:
                        styles.at[i, col_chip] = orange
                        styles.at[i, col_chps] = orange

                elif role.lower() == "defense":
                    if not _ar_green:
                        styles.at[i, col_arm]  = orange
                        styles.at[i, col_arms] = orange
                    if not _ra_green:
                        styles.at[i, col_rad]  = orange
                        styles.at[i, col_rads] = orange

                elif role.lower() == "support":
                    if not _rg_green:
                        styles.at[i, col_rg]  = orange
                        styles.at[i, col_rgs] = orange
                    if not _ra_green:
                        styles.at[i, col_rad]  = orange
                        styles.at[i, col_rads] = orange

            return styles

        # Use Pandas Styler to render inline colors and hide the index
        styled = disp.style.apply(style_rows, axis=None).hide(axis="index")
        # Show styled table (st.dataframe ignores styles; st.write renders Styler HTML)
        st.write(styled, unsafe_allow_html=True)

# -------------------------------
# ADD / UPDATE HERO (full-record save)
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

        # Add blank option at top and default to blank
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
                level = st.number_input("Level", min_value=0, max_value=200, step=1, value=int(hero_data.get("level", 0) or 0))
                power = st.number_input("Power", min_value=0, max_value=100_000_000, step=100, value=int(hero_data.get("power", 0) or 0))
                rail_gun = st.number_input("Rail Gun", min_value=0, max_value=999, step=1, value=int(hero_data.get("rail_gun", 0) or 0))
                rail_gun_stars_val = str(hero_data.get("rail_gun_stars", "") or "")
                rail_gun_stars = st.selectbox("Rail Gun Stars", STAR_CHOICES, index=STAR_CHOICES.index(rail_gun_stars_val) if rail_gun_stars_val in STAR_CHOICES else 0)
                armor = st.number_input("Armor", min_value=0, max_value=999, step=1, value=int(hero_data.get("armor", 0) or 0))
                armor_stars_val = str(hero_data.get("armor_stars", "") or "")
                armor_stars = st.selectbox("Armor Stars", STAR_CHOICES, index=STAR_CHOICES.index(armor_stars_val) if armor_stars_val in STAR_CHOICES else 0)
                data_chip = st.number_input("Data Chip", min_value=0, max_value=999, step=1, value=int(hero_data.get("data_chip", 0) or 0))
                data_chip_stars_val = str(hero_data.get("data_chip_stars", "") or "")
                data_chip_stars = st.selectbox("Data Chip Stars", STAR_CHOICES, index=STAR_CHOICES.index(data_chip_stars_val) if data_chip_stars_val in STAR_CHOICES else 0)

            with c2:
                radar = st.number_input("Radar", min_value=0, max_value=999, step=1, value=int(hero_data.get("radar", 0) or 0))
                radar_stars_val = str(hero_data.get("radar_stars", "") or "")
                radar_stars = st.selectbox("Radar Stars", STAR_CHOICES, index=STAR_CHOICES.index(radar_stars_val) if radar_stars_val in STAR_CHOICES else 0)
                weapon = st.selectbox("Weapon", ["Yes", "No"], index=0 if hero_data.get("weapon", False) else 1)
                weapon_level = st.number_input("Weapon Level", min_value=0, max_value=999, step=1, value=int(hero_data.get("weapon_level", 0) or 0))
                max_skill_level = st.number_input("Max Skill Level", min_value=0, max_value=999, step=1, value=int(hero_data.get("max_skill_level", 0) or 0))
                skill1 = st.number_input("Skill 1", min_value=0, max_value=999, step=1, value=int(hero_data.get("skill1", 0) or 0))
                skill2 = st.number_input("Skill 2", min_value=0, max_value=999, step=1, value=int(hero_data.get("skill2", 0) or 0))
                skill3 = st.number_input("Skill 3", min_value=0, max_value=999, step=1, value=int(hero_data.get("skill3", 0) or 0))

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
