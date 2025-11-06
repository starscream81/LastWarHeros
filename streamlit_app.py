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

# Column order (Team immediately after Name)
DISPLAY_COLUMNS = [
    "name","team","type","role","level","power",
    "rail_gun","rail_gun_stars","armor","armor_stars",
    "data_chip","data_chip_stars","radar","radar_stars",
    "weapon","weapon_level","max_skill_level","skill1","skill2","skill3",
]

NUMERIC_NON_STAR = [
    "level","power","rail_gun","armor","data_chip","radar",
    "weapon_level","max_skill_level","skill1","skill2","skill3",
]

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

def safe_int_format(x):
    try:
        if pd.isna(x) or x == "":
            return ""
        return f"{int(float(x)):,}"
    except Exception:
        return x

# -------------------------------
# UI nav
# -------------------------------
if "nav" not in st.session_state:
    st.session_state["nav"] = "Heroes"

page = st.sidebar.radio("Navigate", ["Heroes", "Add / Update Hero", "Dashboard"], key="nav")

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

        # Sort by Team (1–4, then blanks), then by name
        order_map = {"1":1,"2":2,"3":3,"4":4}
        df["__team_sort__"] = df.get("team").map(order_map).fillna(99)
        df = df.sort_values(["__team_sort__","name"]).drop(columns="__team_sort__")

        disp = df.copy()

        # Only show "Yes" for weapon
        if "weapon" in disp.columns:
            disp["weapon"] = disp["weapon"].apply(lambda x: "Yes" if x is True else "")

        # Coerce numeric for formatting
        for c in NUMERIC_NON_STAR:
            if c in disp.columns:
                disp[c] = pd.to_numeric(disp[c], errors="coerce")

        # Blanks instead of None/NaN
        disp = disp.replace({None:""}).fillna("")

        # Select and pretty headers
        show_cols = [c for c in DISPLAY_COLUMNS if c in disp.columns]
        disp = disp[show_cols]
        disp = disp.rename(columns=PRETTY_COLUMNS_MAP)

        # Orange role highlights
        orange = "background-color: #FFA50033;"
        col_rg, col_rgs = PRETTY_COLUMNS_MAP["rail_gun"], PRETTY_COLUMNS_MAP["rail_gun_stars"]
        col_arm, col_arms = PRETTY_COLUMNS_MAP["armor"], PRETTY_COLUMNS_MAP["armor_stars"]
        col_chip, col_chps = PRETTY_COLUMNS_MAP["data_chip"], PRETTY_COLUMNS_MAP["data_chip_stars"]
        col_rad, col_rads = PRETTY_COLUMNS_MAP["radar"], PRETTY_COLUMNS_MAP["radar_stars"]

        def style_rows(_):
            styles = pd.DataFrame("", index=disp.index, columns=disp.columns)
            logic_df = df.reset_index(drop=True)
            for i in disp.index:
                role = str(logic_df.at[i, "role"]).lower() if "role" in logic_df.columns else ""
                if role == "attack":
                    for c in [col_rg,col_rgs,col_chip,col_chps]:
                        styles.at[i, c] = orange
                elif role == "defense":
                    for c in [col_arm,col_arms,col_rad,col_rads]:
                        styles.at[i, c] = orange
                elif role == "support":
                    for c in [col_rg,col_rgs,col_rad,col_rads]:
                        styles.at[i, c] = orange
            return styles

        # Integer formatting on numeric non-star cols
        pretty_numeric = [PRETTY_COLUMNS_MAP[c] for c in NUMERIC_NON_STAR if PRETTY_COLUMNS_MAP.get(c) in disp.columns]
        fmt_map = {col: safe_int_format for col in pretty_numeric}

        styled = (
            disp.style
            .apply(style_rows, axis=None)
            .format(formatter=fmt_map, na_rep="")
            .hide(axis="index")
            .set_table_styles(
                [
                    {"selector":"th","props":[("text-align","center")]},
                    {"selector":"td","props":[("text-align","center")]}
                ]
            )
        )
        # Name cells left-aligned; others centered; headers centered
        styled = styled.set_properties(subset=[PRETTY_COLUMNS_MAP["name"]], **{"text-align":"left"})
        st.write(styled, unsafe_allow_html=True)

# -------------------------------
# ADD / UPDATE HERO (full-record save) + Team field
# -------------------------------
elif page == "Add / Update Hero":
    st.title("➕ Add / Update Hero")

    catalog = load_catalog()
    heroes = load_heroes()

    if catalog.empty:
        st.error("Catalog is empty. Seed hero_catalog first.")
    else:
        merged = catalog.merge(heroes[["name","power","team"]] if not heroes.empty else pd.DataFrame(columns=["name","power","team"]),
                               on="name", how="left")
        merged["power"] = merged["power"].fillna(0)
        merged = merged.sort_values("power", ascending=False)

        options = [""] + [f"{row['name']} (Power: {int(row['power'])})" for _, row in merged.iterrows()]
        selection = st.selectbox("Name", options, index=0)

        if selection == "":
            st.info("Select a hero from the dropdown to view or update their data.")
            st.stop()

        name = selection.split(" (Power")[0]
        row = merged[merged["name"] == name].iloc[0]
        st.caption(f"Type: **{row['type']}**  |  Role: **{row['role']}**  |  Power: **{int(row['power'])}**")

        hero_data = get_hero_record(name)

        # Team dropdown: blank, 1–4
        current_team = str(hero_data.get("team") or "")
        team_options = ["","1","2","3","4"]
        team_index = team_options.index(current_team) if current_team in team_options else 0
        team = st.selectbox("Team", team_options, index=team_index)

        with st.form("hero_full_update"):
            c1, c2 = st.columns(2)
            with c1:
                level = st.number_input("Level", 0, 200, int(hero_data.get("level", 0) or 0))
                power = st.number_input("Power", 0, 100_000_000, int(hero_data.get("power", 0) or 0), 100)
                rail_gun = st.number_input("Rail Gun", 0, 999, int(hero_data.get("rail_gun", 0) or 0))
                rail_gun_stars = st.selectbox("Rail Gun Stars", STAR_CHOICES, index=STAR_CHOICES.index(str(hero_data.get("rail_gun_stars", ""))) if str(hero_data.get("rail_gun_stars", "")) in STAR_CHOICES else 0)
                armor = st.number_input("Armor", 0, 999, int(hero_data.get("armor", 0) or 0))
                armor_stars = st.selectbox("Armor Stars", STAR_CHOICES, index=STAR_CHOICES.index(str(hero_data.get("armor_stars", ""))) if str(hero_data.get("armor_stars", "")) in STAR_CHOICES else 0)
                data_chip = st.number_input("Data Chip", 0, 999, int(hero_data.get("data_chip", 0) or 0))
                data_chip_stars = st.selectbox("Data Chip Stars", STAR_CHOICES, index=STAR_CHOICES.index(str(hero_data.get("data_chip_stars", ""))) if str(hero_data.get("data_chip_stars", "")) in STAR_CHOICES else 0)
            with c2:
                radar = st.number_input("Radar", 0, 999, int(hero_data.get("radar", 0) or 0))
                radar_stars = st.selectbox("Radar Stars", STAR_CHOICES, index=STAR_CHOICES.index(str(hero_data.get("radar_stars", ""))) if str(hero_data.get("radar_stars", "")) in STAR_CHOICES else 0)
                weapon = st.selectbox("Weapon", ["Yes", "No"], index=0 if hero_data.get("weapon", False) else 1)
                weapon_level = st.number_input("Weapon Level", 0, 999, int(hero_data.get("weapon_level", 0) or 0))
                max_skill_level = st.number_input("Max Skill Level", 0, 999, int(hero_data.get("max_skill_level", 0) or 0))
                skill1 = st.number_input("Skill 1", 0, 999, int(hero_data.get("skill1", 0) or 0))
                skill2 = st.number_input("Skill 2", 0, 999, int(hero_data.get("skill2", 0) or 0))
                skill3 = st.number_input("Skill 3", 0, 999, int(hero_data.get("skill3", 0) or 0))
            submitted = st.form_submit_button("Save")

        if submitted:
            fields = {
                "team": team or None,
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
# DASHBOARD (compact header; tight tables; no index; controls on left)
# -------------------------------
else:
    heroes = load_heroes()

    # Header row: image | title; then (under title) Base Level + Total Power
    img_col, hdr_col = st.columns([1, 7])
    with img_col:
        st.image("frog.png", use_column_width=False, width=320)

    with hdr_col:
        st.title("Shōckwave")

        # Directly under the title, to the LEFT (next to picture): Base Level + Total Power
        base_col, total_col, _sp = st.columns([1, 2, 4])
        with base_col:
            # tiny 2-digit text box (no +/-)
            base_level_str = st.text_input(
                "Base Level",
                value=st.session_state.get("base_level_str", ""),
                max_chars=2,
                key="base_level_str",
            )
            if base_level_str and not base_level_str.isdigit():
                st.session_state.base_level_str = "".join(ch for ch in base_level_str if ch.isdigit())[:2]

        with total_col:
            total_power = 0 if heroes.empty else pd.to_numeric(heroes.get("power"), errors="coerce").fillna(0).sum()
            # compact box; fits 13 digits with commas
            st.text_input("Total Hero Power", value=f"{int(total_power):,}", disabled=True, key="total_power")

    if heroes.empty:
        st.info("No hero data yet. Add heroes first in 'Add / Update Hero'.")
        st.stop()

    def render_team_section(team_num: int):
        st.markdown("---")

        # One line: Team X | Type | manual Power (all aligned to the LEFT)
        head, typecol, pcol, _sp = st.columns([1.1, 0.9, 0.9, 5.1])
        with head:
            st.markdown(f"### Team {team_num}")
        with typecol:
            st.selectbox("Type", ["Tank", "Air", "Missile", "Mixed"], key=f"team_type_{team_num}")
        with pcol:
            # Manual Power (10 chars max)
            manual_key = f"team_power_{team_num}_manual"
            st.text_input("Power", value=st.session_state.get(manual_key, ""), max_chars=10, key=manual_key)

        # Table UNDER the header line
        team_df = heroes[heroes.get("team") == str(team_num)].copy()
        team_df["power"] = pd.to_numeric(team_df.get("power"), errors="coerce").fillna(0)
        team_df["level"] = pd.to_numeric(team_df.get("level"), errors="coerce").fillna(0)
        team_df = team_df.sort_values("power", ascending=False)

        top5 = team_df[["name", "level", "power"]].head(5).copy()
        while len(top5) < 5:
            top5 = pd.concat([top5, pd.DataFrame([{"name": "", "level": "", "power": ""}])], ignore_index=True)

        # Only Name | Level | Power; no index
        tdisp = top5.rename(columns={"name": "Name", "level": "Level", "power": "Power"}).reset_index(drop=True)

        def fmt_int(x):
            try:
                if x == "" or pd.isna(x):
                    return ""
                return f"{int(float(x)):,}"
            except Exception:
                return x

        # Tight fixed widths + centered headers & cells
        NAME_W, LEVEL_W, POWER_W = "160px", "80px", "110px"
        tstyled = (
            tdisp.style
            .format({"Level": fmt_int, "Power": fmt_int})
            .hide(axis="index")
            .set_table_styles([
                {"selector": "th", "props": [("text-align", "center"), ("padding", "4px 6px")]},
                {"selector": "td", "props": [("text-align", "center"), ("padding", "4px 6px")]},
            ])
            .set_properties(subset=["Name"],  **{"width": NAME_W})
            .set_properties(subset=["Level"], **{"width": LEVEL_W})
            .set_properties(subset=["Power"], **{"width": POWER_W})
        )
        st.write(tstyled, unsafe_allow_html=True)

    render_team_section(1)
    render_team_section(2)
    render_team_section(3)
    render_team_section(4)
