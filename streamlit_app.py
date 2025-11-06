# -------------------------------
# DASHBOARD (inline header, compact Base Level & Total Power)
# -------------------------------
else:
    heroes = load_heroes()

    # Header: image | [title + base level] | total hero power
    img_col, mid_col, total_col = st.columns([1, 6, 1.4])

    with img_col:
        st.image("frog.png", use_column_width=False, width=320)

    with mid_col:
        # Title + Base Level on the very same line
        tcol, lvlcol = st.columns([5, 0.6])  # tiny col makes the input box small
        with tcol:
            st.title("Shōckwave")
        with lvlcol:
            # 2-digit text box, no +/- buttons
            base_level_str = st.text_input(
                "Base Level",
                value=st.session_state.get("base_level_str", ""),
                max_chars=2,
                key="base_level_str",
            )
            # sanitize to digits only
            if base_level_str and not base_level_str.isdigit():
                st.session_state.base_level_str = "".join(ch for ch in base_level_str if ch.isdigit())[:2]

    with total_col:
        # Compact Total Hero Power on the same line as the title (right side)
        total_power = 0 if heroes.empty else pd.to_numeric(heroes.get("power"), errors="coerce").fillna(0).sum()
        st.text_input(
            "Total Hero Power",
            value=f"{int(total_power):,}",
            disabled=True,
            key="total_power",
        )

    if heroes.empty:
        st.info("No hero data yet. Add heroes first in 'Add / Update Hero'.")
        st.stop()

    def render_team_section(team_num: int):
        st.markdown("---")

        # Header line: Team X | Type | manual Power (same line)
        head, typecol, pcol = st.columns([2, 1, 1])
        with head:
            st.markdown(f"### Team {team_num}")
        with typecol:
            st.selectbox("Type", ["Tank", "Air", "Missile", "Mixed"], key=f"team_type_{team_num}")
        with pcol:
            # Manual Power input (no calculation), 10 characters max
            manual_key = f"team_power_{team_num}_manual"
            st.text_input("Power", value=st.session_state.get(manual_key, ""), max_chars=10, key=manual_key)

        # Table under the header
        team_df = heroes[heroes.get("team") == str(team_num)].copy()
        team_df["power"] = pd.to_numeric(team_df.get("power"), errors="coerce").fillna(0)
        team_df["level"] = pd.to_numeric(team_df.get("level"), errors="coerce").fillna(0)
        team_df = team_df.sort_values("power", ascending=False)

        top5 = team_df[["name", "level", "power"]].head(5).copy()
        while len(top5) < 5:
            top5 = pd.concat([top5, pd.DataFrame([{"name": "", "level": "", "power": ""}])], ignore_index=True)

        tdisp = top5.rename(columns={"name": "Name", "level": "Level", "power": "Power"}).reset_index(drop=True)

        def fmt_int(x):
            try:
                if x == "" or pd.isna(x):
                    return ""
                return f"{int(float(x)):,}"
            except Exception:
                return x

        # compute tight widths per column
        def max_len(series, numeric=False):
            if numeric:
                s = series.apply(fmt_int)
            else:
                s = series.astype(str)
            return max((len(v) for v in s.fillna("").tolist()), default=0)

        name_w  = max_len(tdisp["Name"],  numeric=False)
        level_w = max_len(tdisp["Level"], numeric=True)
        power_w = max_len(tdisp["Power"], numeric=True)

        def to_px(chars, pad=18, min_px=80, max_px=260):
            return f"{min(max(min_px, chars * 8 + pad), max_px)}px"

        name_px  = to_px(name_w,  pad=24, min_px=120, max_px=240)
        level_px = to_px(level_w, pad=18, min_px=90,  max_px=140)
        power_px = to_px(power_w, pad=18, min_px=110, max_px=180)

        # Center headers and cells, hide index, apply tight widths
        tstyled = (
            tdisp.style
            .format({"Level": fmt_int, "Power": fmt_int})
            .hide(axis="index")
            .set_table_styles([
                {"selector": "th", "props": [("text-align", "center"), ("padding", "4px 6px")]},
                {"selector": "td", "props": [("text-align", "center"), ("padding", "4px 6px")]},
            ])
            .set_properties(subset=["Name"],  **{"width": name_px})
            .set_properties(subset=["Level"], **{"width": level_px})
            .set_properties(subset=["Power"], **{"width": power_px})
        )
        st.write(tstyled, unsafe_allow_html=True)

    render_team_section(1)
    render_team_section(2)
    render_team_section(3)
    render_team_section(4)
