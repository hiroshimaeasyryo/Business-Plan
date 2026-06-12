import hmac
import json
import os

import altair as alt
import pandas as pd
import streamlit as st


TYPE_LABELS = {"business": "事業部", "common": "共通部門"}
TYPE_VALUES = list(TYPE_LABELS.values())
GOAL_MODES = {"amount": "目標営業利益額", "margin": "目標営業利益率"}
ALLOCATION_MODES = {
    "contribution": "限界利益シェア",
    "sales": "売上シェア",
    "gross": "粗利シェア",
    "equal": "均等",
    "custom": "カスタム",
}
COMMON_ALLOCATION_MODES = {"none": "配賦しない", **ALLOCATION_MODES}


st.set_page_config(
    page_title="2027年9月期 事業計画シミュレーター",
    layout="wide",
    initial_sidebar_state="expanded",
)


def get_secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return default


def require_password() -> None:
    configured_password = get_secret("APP_PASSWORD") or os.environ.get("APP_PASSWORD", "")
    if not configured_password:
        st.error("APP_PASSWORD が未設定です。`.streamlit/secrets.toml` または公開先のSecretsに設定してください。")
        st.stop()

    if st.session_state.get("authenticated"):
        return

    st.title("事業計画シミュレーター")
    password = st.text_input("パスワード", type="password")
    if st.button("ログイン", type="primary"):
        if hmac.compare_digest(password, configured_password):
            st.session_state.authenticated = True
            st.rerun()
        st.error("パスワードが違います。")
    st.stop()


def sample_rows() -> list[dict]:
    return [
        {
            "type": "事業部",
            "name": "広告事業",
            "sales": 24000.0,
            "cogs": 9600.0,
            "variable_sga": 3600.0,
            "fixed_sga": 4200.0,
            "custom_weight": 4.0,
        },
        {
            "type": "事業部",
            "name": "SaaS事業",
            "sales": 18000.0,
            "cogs": 2700.0,
            "variable_sga": 1800.0,
            "fixed_sga": 5200.0,
            "custom_weight": 5.0,
        },
        {
            "type": "事業部",
            "name": "受託開発事業",
            "sales": 15000.0,
            "cogs": 8400.0,
            "variable_sga": 1200.0,
            "fixed_sga": 2600.0,
            "custom_weight": 2.0,
        },
        {
            "type": "共通部門",
            "name": "本部",
            "sales": 0.0,
            "cogs": 0.0,
            "variable_sga": 0.0,
            "fixed_sga": 4800.0,
            "custom_weight": 1.0,
        },
    ]


def blank_row(row_type: str, name: str) -> dict:
    return {
        "type": row_type,
        "name": name,
        "sales": 0.0,
        "cogs": 0.0,
        "variable_sga": 0.0,
        "fixed_sga": 0.0,
        "custom_weight": 1.0,
    }


def init_state() -> None:
    defaults = {
        "actual_months": 6,
        "goal_mode": "amount",
        "goal_value": 8000.0,
        "profit_allocation_mode": "contribution",
        "common_allocation_mode": "sales",
        "rows_df": pd.DataFrame(sample_rows()),
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def display_number(value: float) -> str:
    if pd.isna(value):
        return "-"
    return f"{value:,.1f}" if abs(value) < 1000 else f"{value:,.0f}"


def display_percent(value: float) -> str:
    if pd.isna(value):
        return "-"
    return f"{value * 100:.1f}%"


def normalize_rows(df: pd.DataFrame) -> pd.DataFrame:
    expected = ["type", "name", "sales", "cogs", "variable_sga", "fixed_sga", "custom_weight"]
    for column in expected:
        if column not in df.columns:
            df[column] = "" if column in {"type", "name"} else 0.0
    df = df[expected].copy()
    df["type"] = df["type"].map({"business": "事業部", "common": "共通部門"}).fillna(df["type"])
    df.loc[~df["type"].isin(TYPE_VALUES), "type"] = "事業部"
    df["name"] = df["name"].fillna("").astype(str)
    for column in ["sales", "cogs", "variable_sga", "fixed_sga", "custom_weight"]:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    return df


def annualized_rows(df: pd.DataFrame, actual_months: int) -> pd.DataFrame:
    rows = normalize_rows(df)
    factor = 12 / max(actual_months, 1)
    rows["annual_sales"] = rows["sales"] * factor
    rows["annual_cogs"] = rows["cogs"] * factor
    rows["annual_variable_sga"] = rows["variable_sga"] * factor
    rows["annual_fixed_sga"] = rows["fixed_sga"] * factor
    rows["gross_profit"] = rows["annual_sales"] - rows["annual_cogs"]
    rows["contribution"] = rows["gross_profit"] - rows["annual_variable_sga"]
    rows["op_profit"] = rows["contribution"] - rows["annual_fixed_sga"]
    rows["cogs_ratio"] = rows["annual_cogs"].div(rows["annual_sales"]).where(rows["annual_sales"] > 0, 0)
    rows["variable_sga_ratio"] = rows["annual_variable_sga"].div(rows["annual_sales"]).where(rows["annual_sales"] > 0, 0)
    rows["contribution_margin_ratio"] = rows["contribution"].div(rows["annual_sales"]).where(rows["annual_sales"] > 0, 0)
    return rows


def weights(rows: pd.DataFrame, mode: str) -> pd.Series:
    if rows.empty:
        return pd.Series(dtype=float)
    if mode == "equal":
        return pd.Series([1 / len(rows)] * len(rows), index=rows.index)
    if mode == "custom":
        raw = rows["custom_weight"].clip(lower=0)
    elif mode == "sales":
        raw = rows["annual_sales"].clip(lower=0)
    elif mode == "gross":
        raw = rows["gross_profit"].clip(lower=0)
    else:
        raw = rows["contribution"].clip(lower=0)
    total = raw.sum()
    if total <= 0:
        return pd.Series([1 / len(rows)] * len(rows), index=rows.index)
    return raw / total


def compute_scenario(
    df: pd.DataFrame,
    actual_months: int,
    goal_mode: str,
    goal_value: float,
    profit_allocation_mode: str,
    common_allocation_mode: str,
) -> dict:
    rows = annualized_rows(df, actual_months)
    business = rows[rows["type"] == "事業部"].copy()
    common = rows[rows["type"] == "共通部門"].copy()
    warnings = []

    if business.empty:
        warnings.append("少なくとも1つの事業部が必要です。")

    invalid = business[business["contribution_margin_ratio"] <= 0]["name"].tolist()
    if invalid:
        warnings.append("限界利益率が0%以下の事業部があります: " + "、".join(invalid))

    profit_weights = weights(business, profit_allocation_mode)
    common_weights = weights(business, common_allocation_mode)
    common_op = common["op_profit"].sum()
    common_sales = common["annual_sales"].sum()

    sales_base = (
        business["annual_fixed_sga"].div(business["contribution_margin_ratio"])
        .where(business["contribution_margin_ratio"] > 0, 0)
        .sum()
    )
    profit_slope = (
        profit_weights.div(business["contribution_margin_ratio"])
        .where(business["contribution_margin_ratio"] > 0, 0)
        .sum()
    )

    target_company_op = float(goal_value)
    if goal_mode == "margin":
        target_margin = goal_value / 100
        denominator = 1 - target_margin * profit_slope
        numerator = target_margin * (common_sales + sales_base - profit_slope * common_op)
        if denominator <= 0:
            warnings.append("指定した目標営業利益率では解が成立しません。限界利益率や配分方法を見直してください。")
        else:
            target_company_op = numerator / denominator

    business_profit_pool = target_company_op - common_op
    target = business.copy()
    target["profit_weight"] = profit_weights
    target["common_weight"] = common_weights if common_allocation_mode != "none" else 0
    target["direct_op"] = business_profit_pool * target["profit_weight"]
    target["required_sales"] = (
        (target["annual_fixed_sga"] + target["direct_op"])
        .div(target["contribution_margin_ratio"])
        .where(target["contribution_margin_ratio"] > 0)
    )
    target["required_cogs"] = target["required_sales"] * target["cogs_ratio"]
    target["required_gross_profit"] = target["required_sales"] - target["required_cogs"]
    target["required_variable_sga"] = target["required_sales"] * target["variable_sga_ratio"]
    target["required_fixed_sga"] = target["annual_fixed_sga"]
    target["required_total_sga"] = target["required_variable_sga"] + target["required_fixed_sga"]
    target["common_allocation"] = (-common_op if common_allocation_mode != "none" else 0) * target["common_weight"]
    target["allocated_op"] = target["direct_op"] - target["common_allocation"]
    target["direct_op_margin"] = target["direct_op"].div(target["required_sales"])
    target["allocated_op_margin"] = target["allocated_op"].div(target["required_sales"])
    target["break_even_sales"] = target["annual_fixed_sga"].div(target["contribution_margin_ratio"]).where(
        target["contribution_margin_ratio"] > 0
    )
    target["sales_gap"] = target["required_sales"] - target["annual_sales"]

    current_sales = rows["annual_sales"].sum()
    current_op = rows["op_profit"].sum()
    target_sales = target["required_sales"].sum() + common_sales
    target_direct_op = target["direct_op"].sum()
    target_allocated_op = target["allocated_op"].sum()
    target_op_margin = target_company_op / target_sales if target_sales else 0
    target_direct_margin = target_direct_op / target_sales if target_sales else 0

    summary = {
        "current_sales": current_sales,
        "current_op": current_op,
        "target_sales": target_sales,
        "target_cogs": target["required_cogs"].sum() + common["annual_cogs"].sum(),
        "target_gross_profit": target["required_gross_profit"].sum() + common["gross_profit"].sum(),
        "target_variable_sga": target["required_variable_sga"].sum() + common["annual_variable_sga"].sum(),
        "target_fixed_sga": target["required_fixed_sga"].sum() + common["annual_fixed_sga"].sum(),
        "target_direct_op": target_direct_op,
        "target_direct_margin": target_direct_margin,
        "target_allocated_op": target_allocated_op,
        "target_company_op": target_company_op,
        "target_op_margin": target_op_margin,
        "common_op": common_op,
        "common_burden": -common_op if common_allocation_mode != "none" else 0,
        "sales_gap": target_sales - current_sales,
    }

    return {"rows": rows, "target": target, "summary": summary, "warnings": warnings}


def to_state_json() -> str:
    payload = {
        "actualMonths": st.session_state.actual_months,
        "goalMode": st.session_state.goal_mode,
        "goalValue": st.session_state.goal_value,
        "profitAllocationMode": st.session_state.profit_allocation_mode,
        "commonAllocationMode": st.session_state.common_allocation_mode,
        "rows": normalize_rows(st.session_state.rows_df).rename(
            columns={"variable_sga": "variableSga", "fixed_sga": "fixedSga", "custom_weight": "customWeight"}
        ).assign(type=lambda df: df["type"].map({"事業部": "business", "共通部門": "common"})).to_dict("records"),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def load_json(uploaded_file) -> None:
    payload = json.loads(uploaded_file.getvalue().decode("utf-8"))
    rows = pd.DataFrame(payload.get("rows", []))
    rows = rows.rename(columns={"variableSga": "variable_sga", "fixedSga": "fixed_sga", "customWeight": "custom_weight"})
    st.session_state.rows_df = normalize_rows(rows)
    st.session_state.actual_months = int(payload.get("actualMonths", 6))
    st.session_state.goal_mode = payload.get("goalMode", "amount")
    st.session_state.goal_value = float(payload.get("goalValue", 8000))
    st.session_state.profit_allocation_mode = payload.get("profitAllocationMode", "contribution")
    st.session_state.common_allocation_mode = payload.get("commonAllocationMode", "sales")


def format_table(df: pd.DataFrame) -> pd.DataFrame:
    view = df[
        [
            "name",
            "annual_sales",
            "required_sales",
            "required_cogs",
            "required_gross_profit",
            "required_variable_sga",
            "required_fixed_sga",
            "required_total_sga",
            "direct_op",
            "direct_op_margin",
            "common_allocation",
            "allocated_op",
            "allocated_op_margin",
            "contribution_margin_ratio",
            "break_even_sales",
            "sales_gap",
        ]
    ].copy()
    view.columns = [
        "名称",
        "現状売上(年換算)",
        "必要売上高",
        "必要売上原価",
        "必要売上総利益",
        "必要販管費(変動)",
        "必要販管費(固定)",
        "必要販管費(合計)",
        "事業部直接営業利益",
        "事業部直接営業利益率",
        "本部費配賦額",
        "本部費配賦後営業利益",
        "本部費配賦後営業利益率",
        "限界利益率",
        "損益分岐点売上高",
        "売上ギャップ",
    ]
    return view


def metric_card(label: str, value: float, suffix: str = "") -> None:
    st.metric(label, f"{display_number(value)}{suffix}")


def render_charts(target: pd.DataFrame, summary: dict) -> None:
    sales_chart_df = target.melt(
        id_vars=["name"],
        value_vars=["annual_sales", "required_sales"],
        var_name="区分",
        value_name="金額",
    )
    sales_chart_df["区分"] = sales_chart_df["区分"].map({"annual_sales": "現状売上", "required_sales": "必要売上"})
    sales_chart = (
        alt.Chart(sales_chart_df)
        .mark_bar()
        .encode(
            x=alt.X("name:N", title="事業部"),
            y=alt.Y("金額:Q", title="金額"),
            color=alt.Color("区分:N", title=""),
            xOffset="区分:N",
            tooltip=["name", "区分", alt.Tooltip("金額:Q", format=",.1f")],
        )
        .properties(height=320)
    )
    st.altair_chart(sales_chart, use_container_width=True)

    cost_df = target[
        ["name", "required_cogs", "required_variable_sga", "required_fixed_sga", "direct_op"]
    ].melt(id_vars=["name"], var_name="区分", value_name="金額")
    cost_df["区分"] = cost_df["区分"].map(
        {
            "required_cogs": "売上原価",
            "required_variable_sga": "販管費(変動)",
            "required_fixed_sga": "販管費(固定)",
            "direct_op": "事業部直接営業利益",
        }
    )
    cost_chart = (
        alt.Chart(cost_df)
        .mark_bar()
        .encode(
            x=alt.X("name:N", title="事業部"),
            y=alt.Y("金額:Q", title="金額"),
            color=alt.Color("区分:N", title=""),
            tooltip=["name", "区分", alt.Tooltip("金額:Q", format=",.1f")],
        )
        .properties(height=320)
    )
    st.altair_chart(cost_chart, use_container_width=True)

    margin_df = target[["name", "direct_op_margin", "allocated_op_margin", "contribution_margin_ratio"]].melt(
        id_vars=["name"], var_name="区分", value_name="利益率"
    )
    margin_df["区分"] = margin_df["区分"].map(
        {
            "direct_op_margin": "事業部直接営業利益率",
            "allocated_op_margin": "本部費配賦後営業利益率",
            "contribution_margin_ratio": "限界利益率",
        }
    )
    margin_chart = (
        alt.Chart(margin_df)
        .mark_bar()
        .encode(
            x=alt.X("name:N", title="事業部"),
            y=alt.Y("利益率:Q", title="利益率", axis=alt.Axis(format="%")),
            color=alt.Color("区分:N", title=""),
            xOffset="区分:N",
            tooltip=["name", "区分", alt.Tooltip("利益率:Q", format=".1%")],
        )
        .properties(height=320)
    )
    st.altair_chart(margin_chart, use_container_width=True)

    options = {"全社(事業部合算 + 共通費)": None} | {name: idx for idx, name in zip(target.index, target["name"])}
    selected = st.selectbox("損益分岐点グラフの表示対象", list(options.keys()))
    if options[selected] is None:
        business_sales = target["annual_sales"].sum()
        variable_cost = target["annual_cogs"].sum() + target["annual_variable_sga"].sum()
        fixed_cost = summary["target_fixed_sga"]
        variable_ratio = variable_cost / business_sales if business_sales else 0
        current_sales = business_sales
        required_sales = target["required_sales"].sum()
    else:
        row = target.loc[options[selected]]
        fixed_cost = row["annual_fixed_sga"]
        variable_ratio = row["cogs_ratio"] + row["variable_sga_ratio"]
        current_sales = row["annual_sales"]
        required_sales = row["required_sales"]

    contribution_ratio = 1 - variable_ratio
    break_even_sales = fixed_cost / contribution_ratio if contribution_ratio > 0 else float("nan")
    max_sales = max(current_sales, required_sales, break_even_sales if pd.notna(break_even_sales) else 0, 1) * 1.25
    points = pd.DataFrame({"売上高": [0, max_sales]})
    points["売上高線"] = points["売上高"]
    points["総費用線"] = fixed_cost + variable_ratio * points["売上高"]
    points["固定費線"] = fixed_cost
    line_df = points.melt("売上高", var_name="線", value_name="金額")
    base = alt.Chart(line_df).mark_line(point=True).encode(
        x=alt.X("売上高:Q", title="売上高"),
        y=alt.Y("金額:Q", title="金額"),
        color=alt.Color("線:N", title=""),
        tooltip=["線", alt.Tooltip("売上高:Q", format=",.1f"), alt.Tooltip("金額:Q", format=",.1f")],
    )
    layers = [base]
    if pd.notna(break_even_sales):
        layers.append(
            alt.Chart(pd.DataFrame({"x": [break_even_sales]}))
            .mark_rule(strokeDash=[6, 4], color="#b4545f")
            .encode(x="x:Q")
        )
    st.altair_chart(alt.layer(*layers).properties(height=360), use_container_width=True)


require_password()
init_state()

st.title("2027年9月期 事業計画シミュレーター")

with st.sidebar:
    st.header("前提条件")
    st.session_state.actual_months = st.number_input("実績月数", 1, 12, int(st.session_state.actual_months), 1)
    st.session_state.goal_mode = st.radio(
        "全社目標の指定方法",
        list(GOAL_MODES.keys()),
        format_func=GOAL_MODES.get,
        horizontal=True,
        index=list(GOAL_MODES.keys()).index(st.session_state.goal_mode),
    )
    st.session_state.goal_value = st.number_input(
        "全社目標値",
        value=float(st.session_state.goal_value),
        step=100.0 if st.session_state.goal_mode == "amount" else 0.5,
    )
    st.session_state.profit_allocation_mode = st.selectbox(
        "事業部利益配分",
        list(ALLOCATION_MODES.keys()),
        format_func=ALLOCATION_MODES.get,
        index=list(ALLOCATION_MODES.keys()).index(st.session_state.profit_allocation_mode),
    )
    st.session_state.common_allocation_mode = st.selectbox(
        "本部費配賦",
        list(COMMON_ALLOCATION_MODES.keys()),
        format_func=COMMON_ALLOCATION_MODES.get,
        index=list(COMMON_ALLOCATION_MODES.keys()).index(st.session_state.common_allocation_mode),
    )

tabs = st.tabs(["入力", "結果", "グラフ", "保存/読込"])

with tabs[0]:
    st.subheader("事業部・共通部門の実績入力")
    edited = st.data_editor(
        normalize_rows(st.session_state.rows_df),
        hide_index=True,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "type": st.column_config.SelectboxColumn("区分", options=TYPE_VALUES, required=True),
            "name": st.column_config.TextColumn("名称", required=True),
            "sales": st.column_config.NumberColumn("売上", step=0.1),
            "cogs": st.column_config.NumberColumn("売上原価", step=0.1),
            "variable_sga": st.column_config.NumberColumn("販管費(変動)", step=0.1),
            "fixed_sga": st.column_config.NumberColumn("販管費(固定)", step=0.1),
            "custom_weight": st.column_config.NumberColumn("カスタム配分ウェイト", step=0.1),
        },
    )
    st.session_state.rows_df = normalize_rows(edited)
    col1, col2, col3 = st.columns([1, 1, 4])
    if col1.button("事業部を追加"):
        st.session_state.rows_df = pd.concat(
            [st.session_state.rows_df, pd.DataFrame([blank_row("事業部", "新規事業部")])],
            ignore_index=True,
        )
        st.rerun()
    if col2.button("共通部門を追加"):
        st.session_state.rows_df = pd.concat(
            [st.session_state.rows_df, pd.DataFrame([blank_row("共通部門", "共通部門")])],
            ignore_index=True,
        )
        st.rerun()

scenario = compute_scenario(
    st.session_state.rows_df,
    st.session_state.actual_months,
    st.session_state.goal_mode,
    st.session_state.goal_value,
    st.session_state.profit_allocation_mode,
    st.session_state.common_allocation_mode,
)

with tabs[1]:
    for warning in scenario["warnings"]:
        st.warning(warning)
    summary = scenario["summary"]
    cols = st.columns(4)
    with cols[0]:
        metric_card("全社必要売上高", summary["target_sales"])
    with cols[1]:
        metric_card("事業部直接営業利益合計", summary["target_direct_op"])
        st.caption(f"利益率 {display_percent(summary['target_direct_margin'])}")
    with cols[2]:
        metric_card("本部費配賦後営業利益合計", summary["target_company_op"])
        st.caption(f"利益率 {display_percent(summary['target_op_margin'])}")
    with cols[3]:
        metric_card("売上ギャップ", summary["sales_gap"])

    st.subheader("事業部別の必要予算")
    result_table = format_table(scenario["target"])
    st.dataframe(
        result_table.style.format(
            {
                "現状売上(年換算)": "{:,.1f}",
                "必要売上高": "{:,.1f}",
                "必要売上原価": "{:,.1f}",
                "必要売上総利益": "{:,.1f}",
                "必要販管費(変動)": "{:,.1f}",
                "必要販管費(固定)": "{:,.1f}",
                "必要販管費(合計)": "{:,.1f}",
                "事業部直接営業利益": "{:,.1f}",
                "事業部直接営業利益率": "{:.1%}",
                "本部費配賦額": "{:,.1f}",
                "本部費配賦後営業利益": "{:,.1f}",
                "本部費配賦後営業利益率": "{:.1%}",
                "限界利益率": "{:.1%}",
                "損益分岐点売上高": "{:,.1f}",
                "売上ギャップ": "{:,.1f}",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

with tabs[2]:
    render_charts(scenario["target"], scenario["summary"])

with tabs[3]:
    st.subheader("保存/読込")
    json_text = to_state_json()
    st.download_button(
        "入力データをJSON保存",
        json_text,
        file_name="business-plan-simulator.json",
        mime="application/json",
    )
    st.download_button(
        "結果をCSV保存",
        format_table(scenario["target"]).to_csv(index=False).encode("utf-8-sig"),
        file_name="business-plan-result.csv",
        mime="text/csv",
    )
    uploaded = st.file_uploader("JSONを読込", type=["json"])
    if uploaded is not None:
        try:
            load_json(uploaded)
            st.success("JSONを読込みました。")
            st.rerun()
        except Exception as exc:
            st.error(f"JSONの読込に失敗しました: {exc}")
