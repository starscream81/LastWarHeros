# -------------------------------
# DASHBOARD (data-connected, updated layout)
# -------------------------------
else:
    # pull heroes first so we can show Total Power in the header area
    heroes = load_heroes()
    if heroes.empty:
        st.title("Shōckwave")
        st.info("No hero data yet. Add heroes first in 'Add / Update Hero'.")
        st.stop()

    total_power = pd.to_numeric(heroes.get("power"), errors="coerce").fillna(0).sum()

    # Header row: image on left; on right -> title + Base Level (2-digit), then Total Hero Power under title
    img_col, hdr_col = st.columns([1, 5])
    with img_col:
        st.image("frog.png", use_column_width=False, width=320)

    with hdr_col:
        tcol, lvlcol = st.columns([5, 1])
        with tcol:
            st.title("Shōckwave")
        with lvlcol:
            # 2-digit Base Level box right of the title
            base_level = st.number_input("Base Level", min_value=0, max_value=99, step=1, format="%d", key="base_level")

        # directly under the title, still in the header area (beside the picture)
        p1, p2 = st.columns([4, 2])
        with p1:
            st.text_input("Total Hero Power", value=f"{int(total_power):,}", disabled=True, key="total_power")

    # Helper to render team sections
    def render_team_section(team_num: int):
        st.markdown("---")
        # One line: Team X | Type dropdown | Power box | then the 5-row list to the right
        head, typecol, pcol, listcol = st.columns([1.3, 1.0, 1.0, 6.7])

        with head:
            st.markdown(f"### Team {team_num}")

        with typecol:
            st.selectbox("Type", ["Tank","Air","Missile","Mixed"], key=f"team_type_{team_num}")

        # Filter this team's heroes and compute its power
        team_df = heroes[heroes.get("team") == str(team_num)].copy()
        team_df["power"] = pd.to_numeric(team_df.get("power"), errors="coerce").fillna(0)
        team_df["level"] = pd.to_numeric(team_df.get("level"), errors="coerce").fillna(0)
        team_df = team_df.sort_values("power", ascending=False)

        team_power_sum = int(team_df["power"].sum())
        with pcol:
            st.text_input("Power", value=f"{team_power_sum:,}", disabled=True, key=f"team_power_{team_num}")

        # Top 5 Name, Level, Power (ordered by power); pad blanks to always show 5 rows
        top5 = team_df[["name","level","power"]].head(5).copy()
        while len(top5) < 5:
            top5 = pd.concat([top5, pd.DataFrame([{"name":"","level":"","power":""}])], ignore_index=True)

                with listcol:
            tdisp = top5.rename(columns={"name": "Name", "level": "Level", "power": "Power"}).reset_index(drop=True)

            def fmt_int(x):
                try:
                    if x == "" or pd.isna(x):
                        return ""
                    return f"{int(float(x)):,}"
                except Exception:
                    return x

            tstyled = tdisp.style.format({"Level": fmt_int, "Power": fmt_int}).hide(axis="index")
            st.write(tstyled, unsafe_allow_html=True)

    render_team_section(1)
    render_team_section(2)
    render_team_section(3)
    render_team_section(4)
