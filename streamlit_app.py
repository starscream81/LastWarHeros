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
        
# --- Dashboard settings persistence (Supabase) ---
# --- Dashboard settings persistence (Supabase) ---
def load_settings() -> dict:
    try:
        data = sb.table("dashboard_settings").select("*").eq("id", 1).execute().data
        if data:
            return data[0]
        # seed row if missing (only 1..3)
        sb.table("dashboard_settings").insert({
            "id": 1,
            "base_level": "",
            "team1_power": "",
            "team2_power": "",
            "team3_power": ""
        }).execute()
        return {"id": 1, "base_level": "", "team1_power": "", "team2_power": "", "team3_power": ""}
    except Exception as e:
        st.warning(f"Load failed: {e}")
        return {"id": 1, "base_level": "", "team1_power": "", "team2_power": "", "team3_power": ""}

def save_settings_from_state():
    payload = {
        "id": 1,
        "base_level": st.session_state.get("base_level_str", ""),
        "team1_power": st.session_state.get("team_power_1_manual", ""),
        "team2_power": st.session_state.get("team_power_2_manual", ""),
        "team3_power": st.session_state.get("team_power_3_manual", "")
    }
    try:
        sb.table("dashboard_settings").upsert(payload).execute()
    except Exception as e:
        st.warning(f"Save failed: {e}")

def safe_int_format(x):
    try:
        if pd.isna(x) or x == "":
            return ""
        return f"{int(float(x)):,}"
    except Exception:
        return x

# -------------------------------
# UI nav with password gating (includes Buildings)
# -------------------------------
APP_PASSWORD = "fuckoff"  # change if you want

st.sidebar.markdown("### 🔑 Access")
entered_password = st.sidebar.text_input("Enter password", type="password")

authenticated = entered_password == APP_PASSWORD
if authenticated:
    st.session_state["auth"] = True
elif "auth" not in st.session_state:
    st.session_state["auth"] = False

if st.session_state["auth"]:
    nav_options = ["Dashboard", "Buildings", "Heroes", "Add / Update Hero"]
else:
    nav_options = ["Dashboard"]

if "nav" not in st.session_state or st.session_state["nav"] not in nav_options:
    st.session_state["nav"] = "Dashboard"

page = st.sidebar.radio("Navigate", nav_options, key="nav")

st.sidebar.caption("✅ Access granted" if st.session_state["auth"] else "🔒 Other pages locked until password entered.")



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
# BUILDINGS PAGE (text boxes instead of dropdowns)
# -------------------------------
elif page == "Buildings":
    st.title("🏗️ Buildings")

    # pull HQ level from Dashboard (persisted or current session)
    base_level_str = st.session_state.get("base_level_str", "") or ""
    try:
        hq_level = int(base_level_str) if base_level_str.isdigit() else 0
    except Exception:
        hq_level = 0
    hq_level = max(0, min(999, hq_level))  # clamp for safety

    # Define sections (same structure)
    sections = [
        ("Headquarters", "hq", False),
        ("Wall", "wall", False),

        ("Tech Centers:", None, True),
        ("Tech Center 1", "tech_center_1", False),
        ("Tech Center 2", "tech_center_2", False),
        ("Tech Center 3", "tech_center_3", False),

        ("Military Support:", None, True),
        ("Tank Center", "tank_center", False),
        ("Aircraft Center", "aircraft_center", False),
        ("Missile Center", "missile_center", False),
        ("Barracks 1", "barracks_1", False),
        ("Barracks 2", "barracks_2", False),
        ("Barracks 3", "barracks_3", False),
        ("Barracks 4", "barracks_4", False),
        ("Hospital 1", "hospital_1", False),
        ("Hospital 2", "hospital_2", False),
        ("Hospital 3", "hospital_3", False),
        ("Hospital 4", "hospital_4", False),
        ("Training Grounds 1", "training_grounds_1", False),
        ("Training Grounds 2", "training_grounds_2", False),
        ("Training Grounds 3", "training_grounds_3", False),
        ("Training Grounds 4", "training_grounds_4", False),
        ("Emergency Center", "emergency_center", False),
        ("1st Squad", "squad_1", False),
        ("2nd Squad", "squad_2", False),
        ("3rd Squad", "squad_3", False),
        ("4th Squad", "squad_4", False),
        ("Alert Tower", "alert_tower", False),
        ("Recon Plane 1", "recon_plane_1", False),
        ("Recon Plane 2", "recon_plane_2", False),
        ("Recon Plane 3", "recon_plane_3", False),

        ("Resource Production:", None, True),
        ("Coin Vault", "coin_vault", False),
        ("Iron Warehouse", "iron_warehouse", False),
        ("Food Warehouse", "food_warehouse", False),
        ("Gold Mine 1", "gold_mine_1", False),
        ("Gold Mine 2", "gold_mine_2", False),
        ("Gold Mine 3", "gold_mine_3", False),
        ("Gold Mine 4", "gold_mine_4", False),
        ("Gold Mine 5", "gold_mine_5", False),
        ("Iron Mine 1", "iron_mine_1", False),
        ("Iron Mine 2", "iron_mine_2", False),
        ("Iron Mine 3", "iron_mine_3", False),
        ("Iron Mine 4", "iron_mine_4", False),
        ("Iron Mine 5", "iron_mine_5", False),
        ("Farmland 1", "farmland_1", False),
        ("Farmland 2", "farmland_2", False),
        ("Farmland 3", "farmland_3", False),
        ("Farmland 4", "farmland_4", False),
        ("Farmland 5", "farmland_5", False),
        ("Smelter 1", "smelter_1", False),
        ("Smelter 2", "smelter_2", False),
        ("Smelter 3", "smelter_3", False),
        ("Smelter 4", "smelter_4", False),
        ("Smelter 5", "smelter_5", False),
        ("Traning Base 1", "traning_base_1", False),
        ("Traning Base 2", "traning_base_2", False),
        ("Traning Base 3", "traning_base_3", False),
        ("Traning Base 4", "traning_base_4", False),
        ("Traning Base 5", "traning_base_5", False),
        ("Material Workshop 1", "material_workshop_1", False),
        ("Material Workshop 2", "material_workshop_2", False),
        ("Material Workshop 3", "material_workshop_3", False),
        ("Material Workshop 4", "material_workshop_4", False),
        ("Material Workshop 5", "material_workshop_5", False),
        ("Oil Well 1", "oil_well_1", False),
        ("Oil Well 2", "oil_well_2", False),
        ("Oil Well 3", "oil_well_3", False),
        ("Oil Well 4", "oil_well_4", False),
        ("Oil Well 5", "oil_well_5", False),

        ("Support Buildings:", None, True),
        ("Alliance Support Hub", "alliance_support_hub", False),
        ("Builder's Hut", "builders_hut", False),
        ("Tavern", "tavern", False),
        ("Tactical Institute", "tactical_institute", False),
        ("Drone Parts Workshop", "drone_parts_workshop", False),
        ("Chip Lab", "chip_lab", False),
        ("Component Factory", "component_factory", False),
        ("Gear Factory", "gear_factory", False),
    ]

    # Render rows
    for label, key, is_header in sections:
        if is_header:
            st.subheader(label)
            continue

        c1, c2 = st.columns([2.5, 1.0])
        with c1:
            st.markdown(label)
        with c2:
            if key == "hq":
                st.text_input(
                    "Level",
                    value=str(hq_level) if hq_level > 0 else "",
                    disabled=True,
                    label_visibility="collapsed",
                    key="buildings_hq_level",
                )
            else:
                st.text_input(
                    "Level",
                    value=st.session_state.get(f"buildings_{key}", ""),
                    max_chars=3,
                    key=f"buildings_{key}",
                    label_visibility="collapsed",
                )


# -------------------------------
# DASHBOARD PAGE (complete rebuild, compact teams, working % gradients)
# -------------------------------
else:
    heroes = load_heroes()

    # Load persisted settings
    settings = load_settings()
    for key, default in [
        ("base_level_str", settings.get("base_level", "")),
        ("team_power_1_manual", settings.get("team1_power", "")),
        ("team_power_2_manual", settings.get("team2_power", "")),
        ("team_power_3_manual", settings.get("team3_power", "")),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default or ""

    # Layout
    img_col, hdr_col = st.columns([1, 7])
    with img_col:
        st.image("frog.png", use_column_width=False, width=320)

    with hdr_col:
        st.title("Shōckwave")

        base_col, total_col, _sp = st.columns([1, 2, 4])
        with base_col:
            bl = st.text_input(
                "Base Level",
                value=st.session_state.get("base_level_str", ""),
                max_chars=2,
                key="base_level_str",
                on_change=save_settings_from_state,
            )
            if bl and not bl.isdigit():
                st.session_state.base_level_str = "".join(ch for ch in bl if ch.isdigit())[:2]
                save_settings_from_state()

        with total_col:
            total_power = 0 if heroes.empty else pd.to_numeric(heroes.get("power"), errors="coerce").fillna(0).sum()
            st.text_input("Total Hero Power", value=f"{int(total_power):,}", disabled=True, key="total_power")

    # --------- Teams (compact) ----------
    def render_team_row(team_num: int):
        row_cols = st.columns([1.0, 1.0, 1.0, 7.0])
        with row_cols[0]:
            st.markdown(f"**Team {team_num}**")
        with row_cols[1]:
            st.selectbox("Type", ["Tank", "Air", "Missile", "Mixed"], key=f"team_type_{team_num}")
        with row_cols[2]:
            manual_key = f"team_power_{team_num}_manual"
            st.text_input(
                "Power",
                value=st.session_state.get(manual_key, ""),
                max_chars=10,
                key=manual_key,
                on_change=save_settings_from_state,
            )

    render_team_row(1)
    render_team_row(2)
    render_team_row(3)

    st.markdown("---")

    # --------- Buildings Section ----------
    st.subheader("Buildings")

    st.caption(f"Detected HQ: {''.join(ch for ch in str(st.session_state.get('base_level_str','')) if ch.isdigit()) or st.session_state.get('cached_HQ', 0)}")

    def get_level(key: str) -> int:
        # Safely parse building level, ignoring any non-digits
        raw = str(st.session_state.get(f"buildings_{key}", "") or "")
        digits = "".join(ch for ch in raw if ch.isdigit())
        return int(digits) if digits else 0

    # Determine HQ level robustly (strip all non-digits)
    candidates = [
        st.session_state.get("base_level_str", ""),
        settings.get("base_level", ""),
        st.session_state.get("buildings_hq_level", ""),
    ]
    HQ = 0
    for c in candidates:
        digits = "".join(ch for ch in str(c) if ch.isdigit())
        if digits:
            HQ = int(digits)
            break
    HQ = max(0, min(999, HQ))
    st.session_state["cached_HQ"] = HQ  # cache for reruns

    # TEMP: show what HQ we detected (remove later if you want)
    st.caption(f"Detected HQ: {HQ}")

    # ---------- Helpers ensure they're defined before use ----------
    def fmt_level(n: int) -> str:
        return "" if n <= 0 else str(n)

    # Gradient percent box (0 → red, 100 → green)
    def percent_box(value_pct: str):
        if not value_pct:
            st.markdown("&nbsp;", unsafe_allow_html=True)
            return
        try:
            p = int(value_pct.replace("%", ""))
        except Exception:
            p = 0
        p = max(0, min(150, p))
        r = int(255 * max(0, (100 - p)) / 100)
        g = int(255 * min(100, p) / 100)
        st.markdown(
            f"<div style='display:inline-block;padding:4px 8px;border-radius:6px;"
            f"background:rgb({r},{g},0);color:white;font-weight:600;text-align:center;min-width:70px'>{value_pct}</div>",
            unsafe_allow_html=True,
        )

    # Grouped % = sum(levels) / HQ
    def pct_of_hq(levels: list[int]) -> str:
        vals = [v for v in levels if v > 0]
        if HQ <= 0 or not vals:
            return ""
        pct = round((sum(vals) / HQ) * 100)
        return f"{max(0, min(150, pct))}%"

    # Single % = level / HQ
    def pct_single(level: int) -> str:
        if HQ <= 0 or level <= 0:
            return ""
        pct = round((level / HQ) * 100)
        return f"{max(0, min(150, pct))}%"

    # Row helpers (no headers)
    def row_pair(label1, val1, label2, val2):
        c1, c2, c3, c4 = st.columns([1.2, 0.8, 1.2, 0.8])
        with c1: st.markdown(f"**{label1}**")
        with c2: st.markdown(val1 if val1 else "&nbsp;", unsafe_allow_html=True)
        with c3: st.markdown(f"**{label2}**")
        with c4: st.markdown(val2 if val2 else "&nbsp;", unsafe_allow_html=True)

    def row_pair_pct(label1, pct1, label2=None, pct2=None):
        if label2 is None:
            a, b, _ = st.columns([1.2, 0.8, 2.4])
            with a: st.markdown(f"**{label1}**")
            with b: percent_box(pct1)
        else:
            a, b, c, d = st.columns([1.2, 0.8, 1.2, 0.8])
            with a: st.markdown(f"**{label1}**")
            with b: percent_box(pct1)
            with c: st.markdown(f"**{label2}**")
            with d: percent_box(pct2 or "")

    def pct_group(keys: list[str]) -> str:
        # Consider row “present” if any textbox has any text (even “0”)
        any_filled = any(str(st.session_state.get(f"buildings_{k}", "") or "").strip() != "" for k in keys)
        if HQ <= 0 or not any_filled:
            return ""
        total = 0
        for k in keys:
            raw = str(st.session_state.get(f"buildings_{k}", "") or "")
            digits = "".join(ch for ch in raw if ch.isdigit())
            total += int(digits) if digits else 0
        pct = round((total / HQ) * 100)
        return f"{max(0, min(150, pct))}%"

    def pct_single_key(key: str) -> str:
        raw = str(st.session_state.get(f"buildings_{key}", "") or "").strip()
        if HQ <= 0 or raw == "":
            return ""
        digits = "".join(ch for ch in raw if ch.isdigit())
        val = int(digits) if digits else 0
        pct = round((val / HQ) * 100)
        return f"{max(0, min(150, pct))}%"

    # Top Building Levels
    wall = get_level("wall")
    tc_high = max(get_level("tech_center_1"), get_level("tech_center_2"), get_level("tech_center_3"))
    tam_high = max(get_level("tank_center"), get_level("aircraft_center"), get_level("missile_center"))
    barracks_high = max(get_level("barracks_1"), get_level("barracks_2"), get_level("barracks_3"), get_level("barracks_4"))
    hospital_high = max(get_level("hospital_1"), get_level("hospital_2"), get_level("hospital_3"), get_level("hospital_4"))
    training_high = max(get_level("training_grounds_1"), get_level("training_grounds_2"), get_level("training_grounds_3"), get_level("training_grounds_4"))

    row_pair("Wall:", fmt_level(wall), "Barracks:", fmt_level(barracks_high))
    row_pair("Tech Center:", fmt_level(tc_high), "Hospital:", fmt_level(hospital_high))
    row_pair("Tank/Air/Missile Center:", fmt_level(tam_high), "Training Grounds:", fmt_level(training_high))

    st.write("")

    # Percent table
    # Left side groups (sum/HQ; show 0% if any field present)
    pct_tc   = pct_group(["tech_center_1", "tech_center_2", "tech_center_3"])
    pct_tam  = pct_group(["tank_center", "aircraft_center", "missile_center"])
    pct_bar  = pct_group(["barracks_1", "barracks_2", "barracks_3", "barracks_4"])
    pct_hos  = pct_group(["hospital_1", "hospital_2", "hospital_3", "hospital_4"])
    pct_trn  = pct_group(["training_grounds_1", "training_grounds_2", "training_grounds_3", "training_grounds_4"])
    pct_emg  = pct_single_key("emergency_center")
    pct_sq   = pct_group(["squad_1", "squad_2", "squad_3", "squad_4"])
    pct_alt  = pct_single_key("alert_tower")
    pct_rcn  = pct_group(["recon_plane_1", "recon_plane_2", "recon_plane_3"])

    # Right side resources/support
    pct_oil  = pct_group(["oil_well_1", "oil_well_2", "oil_well_3", "oil_well_4", "oil_well_5"])
    pct_coin = pct_single_key("coin_vault")
    pct_iwh  = pct_single_key("iron_warehouse")
    pct_fwh  = pct_single_key("food_warehouse")
    pct_gold = pct_group(["gold_mine_1", "gold_mine_2", "gold_mine_3", "gold_mine_4", "gold_mine_5"])
    pct_iron = pct_group(["iron_mine_1", "iron_mine_2", "iron_mine_3", "iron_mine_4", "iron_mine_5"])
    pct_farm = pct_group(["farmland_1", "farmland_2", "farmland_3", "farmland_4", "farmland_5"])
    pct_smel = pct_group(["smelter_1", "smelter_2", "smelter_3", "smelter_4", "smelter_5"])
    pct_tbase= pct_group(["traning_base_1", "traning_base_2", "traning_base_3", "traning_base_4", "traning_base_5"])
    pct_mw   = pct_group(["material_workshop_1", "material_workshop_2", "material_workshop_3", "material_workshop_4", "material_workshop_5"])

    pct_hub  = pct_single_key("alliance_support_hub")
    pct_bld  = pct_single_key("builders_hut")
    pct_tav  = pct_single_key("tavern")
    pct_tac  = pct_single_key("tactical_institute")

    # Render rows (with gradient %)
    row_pair_pct("Tech Center:", pct_tc, "Oil Well", pct_oil)
    row_pair_pct("Tank/Air/Missile:", pct_tam, "Coin Vault", pct_coin)
    row_pair_pct("Barracks:", pct_bar, "Iron Warehouse", pct_iwh)
    row_pair_pct("Hospital:", pct_hos, "Food Warehouse", pct_fwh)
    row_pair_pct("Training Grounds:", pct_trn, "Gold Mine", pct_gold)
    row_pair_pct("Emergency Center:", pct_emg, "Iron Mine", pct_iron)
    row_pair_pct("Squads:", pct_sq, "Farmland", pct_farm)
    row_pair_pct("Alert Tower:", pct_alt, "Smelter", pct_smel)
    row_pair_pct("Recon Plane:", pct_rcn, "Training Base", pct_tbase)
    row_pair_pct("Alliance Hub:", pct_hub, "Material Workshop", pct_mw)
    row_pair_pct("Builder's Hut:", pct_bld, "Tactical Institute:", pct_tac)
    row_pair_pct("Tavern:", pct_tav)
