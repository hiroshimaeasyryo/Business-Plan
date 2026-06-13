import hmac
import io
import json
import os
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st


TYPE_LABELS = {"business": "事業部", "common": "共通部門"}
TYPE_VALUES = list(TYPE_LABELS.values())
MONEY_INPUT_COLUMNS = ["sales", "cogs", "variable_sga", "fixed_sga", "planned_fixed_sga"]
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


def get_secret_dict(name: str) -> dict:
    try:
        value = st.secrets.get(name, {})
        return dict(value) if value else {}
    except Exception:
        return {}


def normalize_private_key(service_account_info: dict) -> dict:
    if not service_account_info:
        return {}
    info = dict(service_account_info)
    private_key = info.get("private_key")
    if isinstance(private_key, str):
        info["private_key"] = private_key.replace("\\n", "\n")
    return info


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
            "planned_fixed_sga": 8400.0,
            "custom_weight": 4.0,
        },
        {
            "type": "事業部",
            "name": "SaaS事業",
            "sales": 18000.0,
            "cogs": 2700.0,
            "variable_sga": 1800.0,
            "fixed_sga": 5200.0,
            "planned_fixed_sga": 10400.0,
            "custom_weight": 5.0,
        },
        {
            "type": "事業部",
            "name": "受託開発事業",
            "sales": 15000.0,
            "cogs": 8400.0,
            "variable_sga": 1200.0,
            "fixed_sga": 2600.0,
            "planned_fixed_sga": 5200.0,
            "custom_weight": 2.0,
        },
        {
            "type": "共通部門",
            "name": "本部",
            "sales": 0.0,
            "cogs": 0.0,
            "variable_sga": 0.0,
            "fixed_sga": 4800.0,
            "planned_fixed_sga": 9600.0,
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
        "planned_fixed_sga": 0.0,
        "custom_weight": 1.0,
    }


def init_state() -> None:
    defaults = {
        "actual_months": 6,
        "goal_mode": "amount",
        "goal_value": 8000.0,
        "profit_allocation_mode": "contribution",
        "common_allocation_mode": "sales",
        "use_fixed_cost_plan": False,
        "rows_df": pd.DataFrame(sample_rows()),
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if "rows_editor_df" not in st.session_state:
        st.session_state.rows_editor_df = input_editor_rows(st.session_state.rows_df)


def display_number(value: float) -> str:
    if pd.isna(value):
        return "-"
    return f"{value:,.0f}"


def display_percent(value: float) -> str:
    if pd.isna(value):
        return "-"
    return f"{value * 100:.1f}%"


def parse_input_number(value) -> float:
    if pd.isna(value):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("¥", "")
    if text in {"", "-"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def normalize_rows(df: pd.DataFrame) -> pd.DataFrame:
    expected = ["type", "name", "sales", "cogs", "variable_sga", "fixed_sga", "planned_fixed_sga", "custom_weight"]
    for column in expected:
        if column not in df.columns:
            df[column] = "" if column in {"type", "name"} else 0.0
    df = df[expected].copy()
    df["type"] = df["type"].map({"business": "事業部", "common": "共通部門"}).fillna(df["type"])
    df.loc[~df["type"].isin(TYPE_VALUES), "type"] = "事業部"
    df["name"] = df["name"].fillna("").astype(str)
    for column in ["sales", "cogs", "variable_sga", "fixed_sga", "planned_fixed_sga", "custom_weight"]:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    return df


def input_editor_rows(df: pd.DataFrame) -> pd.DataFrame:
    rows = normalize_rows(df)
    editor_df = rows.copy()
    for column in MONEY_INPUT_COLUMNS:
        editor_df[column] = editor_df[column].map(display_number)
    return editor_df


def normalize_input_editor_rows(df: pd.DataFrame) -> pd.DataFrame:
    expected = ["type", "name", "sales", "cogs", "variable_sga", "fixed_sga", "planned_fixed_sga", "custom_weight"]
    for column in expected:
        if column not in df.columns:
            df[column] = "" if column in {"type", "name"} else 0.0
    rows = df[expected].copy()
    rows["type"] = rows["type"].map({"business": "事業部", "common": "共通部門"}).fillna(rows["type"])
    rows.loc[~rows["type"].isin(TYPE_VALUES), "type"] = "事業部"
    rows["name"] = rows["name"].fillna("").astype(str)
    for column in MONEY_INPUT_COLUMNS:
        rows[column] = rows[column].map(parse_input_number)
    rows["custom_weight"] = pd.to_numeric(rows["custom_weight"], errors="coerce").fillna(0.0)
    return normalize_rows(rows)


def set_rows_state(df: pd.DataFrame) -> None:
    normalized = normalize_rows(df)
    st.session_state.rows_df = normalized
    st.session_state.rows_editor_df = input_editor_rows(normalized)


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
    use_fixed_cost_plan: bool,
) -> dict:
    rows = annualized_rows(df, actual_months)
    rows["plan_fixed_sga"] = rows["planned_fixed_sga"] if use_fixed_cost_plan else rows["annual_fixed_sga"]
    rows["plan_op_profit"] = rows["contribution"] - rows["plan_fixed_sga"]
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
    common_op = common["plan_op_profit"].sum()
    common_sales = common["annual_sales"].sum()

    sales_base = (
        business["plan_fixed_sga"].div(business["contribution_margin_ratio"])
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
        (target["plan_fixed_sga"] + target["direct_op"])
        .div(target["contribution_margin_ratio"])
        .where(target["contribution_margin_ratio"] > 0)
    )
    target["required_cogs"] = target["required_sales"] * target["cogs_ratio"]
    target["required_gross_profit"] = target["required_sales"] - target["required_cogs"]
    target["required_variable_sga"] = target["required_sales"] * target["variable_sga_ratio"]
    target["required_fixed_sga"] = target["plan_fixed_sga"]
    target["required_total_sga"] = target["required_variable_sga"] + target["required_fixed_sga"]
    target["common_allocation"] = (-common_op if common_allocation_mode != "none" else 0) * target["common_weight"]
    target["allocated_op"] = target["direct_op"] - target["common_allocation"]
    target["direct_op_margin"] = target["direct_op"].div(target["required_sales"])
    target["allocated_op_margin"] = target["allocated_op"].div(target["required_sales"])
    target["break_even_sales"] = target["plan_fixed_sga"].div(target["contribution_margin_ratio"]).where(
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
        "current_cogs": rows["annual_cogs"].sum(),
        "current_gross_profit": rows["gross_profit"].sum(),
        "current_variable_sga": rows["annual_variable_sga"].sum(),
        "current_fixed_sga": rows["annual_fixed_sga"].sum(),
        "current_op": current_op,
        "target_sales": target_sales,
        "target_cogs": target["required_cogs"].sum() + common["annual_cogs"].sum(),
        "target_gross_profit": target["required_gross_profit"].sum() + common["gross_profit"].sum(),
        "target_variable_sga": target["required_variable_sga"].sum() + common["annual_variable_sga"].sum(),
        "target_fixed_sga": target["required_fixed_sga"].sum() + common["plan_fixed_sga"].sum(),
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
        "useFixedCostPlan": st.session_state.use_fixed_cost_plan,
        "rows": normalize_rows(st.session_state.rows_df).rename(
            columns={
                "variable_sga": "variableSga",
                "fixed_sga": "fixedSga",
                "planned_fixed_sga": "plannedFixedSga",
                "custom_weight": "customWeight",
            }
        ).assign(type=lambda df: df["type"].map({"事業部": "business", "共通部門": "common"})).to_dict("records"),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def load_state_payload(payload: dict) -> None:
    rows = pd.DataFrame(payload.get("rows", []))
    rows = rows.rename(
        columns={
            "variableSga": "variable_sga",
            "fixedSga": "fixed_sga",
            "plannedFixedSga": "planned_fixed_sga",
            "customWeight": "custom_weight",
        }
    )
    set_rows_state(rows)
    st.session_state.actual_months = int(payload.get("actualMonths", 6))
    st.session_state.goal_mode = payload.get("goalMode", "amount")
    st.session_state.goal_value = float(payload.get("goalValue", 8000))
    st.session_state.profit_allocation_mode = payload.get("profitAllocationMode", "contribution")
    st.session_state.common_allocation_mode = payload.get("commonAllocationMode", "sales")
    st.session_state.use_fixed_cost_plan = bool(payload.get("useFixedCostPlan", False))


def load_json(uploaded_file) -> None:
    payload = json.loads(uploaded_file.getvalue().decode("utf-8"))
    load_state_payload(payload)


def drive_config() -> tuple[dict, str]:
    folder_id = get_secret("GOOGLE_DRIVE_FOLDER_ID")
    service_account_json = get_secret("GOOGLE_SERVICE_ACCOUNT_JSON")
    service_account_info = {}
    if service_account_json:
        try:
            service_account_info = json.loads(service_account_json)
        except json.JSONDecodeError as exc:
            st.session_state.drive_config_error = (
                "GOOGLE_SERVICE_ACCOUNT_JSON のJSON形式を読み取れませんでした。"
                " `private_key` 内の改行は `\\n` のままにするか、"
                " `[gcp_service_account]` 形式でSecretsに設定してください。"
                f" 詳細: {exc}"
            )
            service_account_info = {}
    else:
        service_account_info = get_secret_dict("gcp_service_account")
    return normalize_private_key(service_account_info), folder_id


def drive_is_configured() -> bool:
    service_account_info, folder_id = drive_config()
    return bool(service_account_info and folder_id)


@st.cache_resource(show_spinner=False)
def get_drive_service(service_account_json: str):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/drive"]
    info = json.loads(service_account_json)
    credentials = service_account.Credentials.from_service_account_info(info, scopes=scopes)
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def drive_service():
    service_account_info, _ = drive_config()
    return get_drive_service(json.dumps(service_account_info, ensure_ascii=False, sort_keys=True))


def list_drive_json_files() -> list[dict]:
    _, folder_id = drive_config()
    service = drive_service()
    query = f"'{folder_id}' in parents and mimeType='application/json' and trashed=false"
    response = (
        service.files()
        .list(
            q=query,
            fields="files(id,name,createdTime,modifiedTime,size)",
            orderBy="modifiedTime desc",
            pageSize=100,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    return response.get("files", [])


@st.cache_data(show_spinner=False, ttl=300)
def get_drive_folder_metadata(folder_id: str, service_account_json: str) -> dict:
    service = get_drive_service(service_account_json)
    return (
        service.files()
        .get(
            fileId=folder_id,
            fields="id,name,mimeType,driveId,parents",
            supportsAllDrives=True,
        )
        .execute()
    )


def validate_drive_target() -> tuple[bool, str]:
    service_account_info, folder_id = drive_config()
    if not service_account_info or not folder_id:
        return False, "Google Drive連携が未設定です。"
    try:
        metadata = get_drive_folder_metadata(
            folder_id,
            json.dumps(service_account_info, ensure_ascii=False, sort_keys=True),
        )
    except Exception as exc:
        return False, f"保存先フォルダの確認に失敗しました: {exc}"

    drive_id = metadata.get("driveId")
    if not drive_id:
        return (
            False,
            "保存先フォルダがマイドライブ上にあります。サービスアカウントではマイドライブに新規保存できません。"
            " Shared Drive上のフォルダを指定し、そのShared Driveまたは対象フォルダにサービスアカウントを追加してください。",
        )
    return True, f"Shared Drive上の保存先を確認しました: {metadata.get('name', folder_id)}"


def upload_json_to_drive(file_name: str, content: str) -> dict:
    from googleapiclient.http import MediaIoBaseUpload

    _, folder_id = drive_config()
    service = drive_service()
    metadata = {"name": file_name, "parents": [folder_id], "mimeType": "application/json"}
    media = MediaIoBaseUpload(io.BytesIO(content.encode("utf-8")), mimetype="application/json", resumable=False)
    return (
        service.files()
        .create(body=metadata, media_body=media, fields="id,name,webViewLink", supportsAllDrives=True)
        .execute()
    )


def download_json_from_drive(file_id: str) -> dict:
    from googleapiclient.http import MediaIoBaseDownload

    service = drive_service()
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buffer.seek(0)
    return json.loads(buffer.read().decode("utf-8"))


def auto_load_latest_drive_file() -> None:
    if st.session_state.get("drive_auto_loaded"):
        return
    st.session_state.drive_auto_loaded = True
    if not drive_is_configured():
        return
    try:
        files = list_drive_json_files()
        st.session_state.drive_files = files
        if not files:
            return
        latest = files[0]
        load_state_payload(download_json_from_drive(latest["id"]))
        st.session_state.drive_loaded_notice = f"Google Driveの最新JSONを読み込みました: {latest['name']}"
    except Exception as exc:
        st.session_state.drive_auto_load_error = f"Google Driveからの自動読込に失敗しました: {exc}"


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
        "本部費配賦額",
        "本部費配賦後営業利益",
        "本部費配賦後営業利益率",
        "限界利益率",
        "損益分岐点売上高",
        "売上ギャップ",
    ]
    return view


def build_result_display_table(df: pd.DataFrame) -> pd.DataFrame:
    view = format_table(df).copy()

    total_sales = view["必要売上高"].sum()
    total_gross = view["必要売上総利益"].sum()
    total_variable_sga = view["必要販管費(変動)"].sum()
    total_fixed_sga = view["必要販管費(固定)"].sum()
    total_allocated_op = view["本部費配賦後営業利益"].sum()
    total_contribution = total_gross - total_variable_sga

    total_row = {
        "名称": "合計",
        "現状売上(年換算)": view["現状売上(年換算)"].sum(),
        "必要売上高": total_sales,
        "必要売上原価": view["必要売上原価"].sum(),
        "必要売上総利益": total_gross,
        "必要販管費(変動)": total_variable_sga,
        "必要販管費(固定)": total_fixed_sga,
        "必要販管費(合計)": view["必要販管費(合計)"].sum(),
        "本部費配賦額": view["本部費配賦額"].sum(),
        "本部費配賦後営業利益": total_allocated_op,
        "本部費配賦後営業利益率": total_allocated_op / total_sales if total_sales else 0,
        "限界利益率": total_contribution / total_sales if total_sales else 0,
        "損益分岐点売上高": total_fixed_sga / (total_contribution / total_sales) if total_sales and total_contribution > 0 else 0,
        "売上ギャップ": view["売上ギャップ"].sum(),
    }

    view = pd.concat([view, pd.DataFrame([total_row])], ignore_index=True)

    money_columns = [
        "現状売上(年換算)",
        "必要売上高",
        "必要売上原価",
        "必要売上総利益",
        "必要販管費(変動)",
        "必要販管費(固定)",
        "必要販管費(合計)",
        "本部費配賦額",
        "本部費配賦後営業利益",
        "損益分岐点売上高",
        "売上ギャップ",
    ]
    percent_columns = [
        "本部費配賦後営業利益率",
        "限界利益率",
    ]

    display_df = view.copy()
    for column in money_columns:
        display_df[column] = display_df[column].map(display_number)
    for column in percent_columns:
        display_df[column] = display_df[column].map(display_percent)
    return display_df


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
            tooltip=["name", "区分", alt.Tooltip("金額:Q", format=",.0f")],
        )
        .properties(height=320)
    )
    st.altair_chart(sales_chart, use_container_width=True)

    cost_df = target[
        ["name", "required_cogs", "required_variable_sga", "required_fixed_sga", "common_allocation", "allocated_op"]
    ].melt(id_vars=["name"], var_name="区分", value_name="金額")
    cost_df["区分"] = cost_df["区分"].map(
        {
            "required_cogs": "売上原価",
            "required_variable_sga": "販管費(変動)",
            "required_fixed_sga": "販管費(固定)",
            "common_allocation": "本部費配賦額",
            "allocated_op": "本部費配賦後営業利益",
        }
    )
    cost_chart = (
        alt.Chart(cost_df)
        .mark_bar()
        .encode(
            x=alt.X("name:N", title="事業部"),
            y=alt.Y("金額:Q", title="金額"),
            color=alt.Color("区分:N", title=""),
            tooltip=["name", "区分", alt.Tooltip("金額:Q", format=",.0f")],
        )
        .properties(height=320)
    )
    st.altair_chart(cost_chart, use_container_width=True)

    margin_df = target[["name", "allocated_op_margin", "contribution_margin_ratio"]].melt(
        id_vars=["name"], var_name="区分", value_name="利益率"
    )
    margin_df["区分"] = margin_df["区分"].map(
        {
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
        fixed_cost = row["plan_fixed_sga"]
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
        tooltip=["線", alt.Tooltip("売上高:Q", format=",.0f"), alt.Tooltip("金額:Q", format=",.0f")],
    )
    layers = [base]
    if pd.notna(break_even_sales):
        layers.append(
            alt.Chart(pd.DataFrame({"x": [break_even_sales]}))
            .mark_rule(strokeDash=[6, 4], color="#b4545f")
            .encode(x="x:Q")
        )
    st.altair_chart(alt.layer(*layers).properties(height=360), use_container_width=True)


def render_result_insights(target: pd.DataFrame, summary: dict) -> None:
    st.subheader("シミュレーション結果の読み取り")

    fixed_delta = summary["target_fixed_sga"] - summary["current_fixed_sga"]
    sales_growth = summary["sales_gap"] / summary["current_sales"] if summary["current_sales"] else 0
    gross_margin = summary["target_gross_profit"] / summary["target_sales"] if summary["target_sales"] else 0

    cols = st.columns(4)
    cols[0].metric("必要売上の増減", display_number(summary["sales_gap"]), f"{sales_growth * 100:.1f}%")
    cols[1].metric("必要粗利率", display_percent(gross_margin))
    cols[2].metric("固定費計画の増減", display_number(fixed_delta))
    cols[3].metric("本部費配賦負担", display_number(summary["common_burden"]))

    composition = pd.DataFrame(
        [
            {"区分": "売上原価", "金額": summary["target_cogs"]},
            {"区分": "販管費(変動)", "金額": summary["target_variable_sga"]},
            {"区分": "販管費(固定)", "金額": summary["target_fixed_sga"]},
            {"区分": "本部費配賦後営業利益", "金額": summary["target_company_op"]},
        ]
    )
    composition_chart = (
        alt.Chart(composition)
        .mark_bar()
        .encode(
            y=alt.Y("区分:N", title="", sort=None),
            x=alt.X("金額:Q", title="金額"),
            color=alt.Color("区分:N", legend=None),
            tooltip=["区分", alt.Tooltip("金額:Q", format=",.0f")],
        )
        .properties(height=180)
    )

    gap_chart = (
        alt.Chart(target.sort_values("sales_gap", ascending=False))
        .mark_bar()
        .encode(
            x=alt.X("sales_gap:Q", title="売上ギャップ"),
            y=alt.Y("name:N", title="", sort="-x"),
            color=alt.condition(alt.datum.sales_gap >= 0, alt.value("#c46a2f"), alt.value("#2b6f77")),
            tooltip=["name", alt.Tooltip("sales_gap:Q", title="売上ギャップ", format=",.0f")],
        )
        .properties(height=max(180, min(420, 44 * len(target))))
    )

    left, right = st.columns(2)
    with left:
        st.caption("全社必要売上の構成")
        st.altair_chart(composition_chart, use_container_width=True)
    with right:
        st.caption("事業部別 売上ギャップ")
        st.altair_chart(gap_chart, use_container_width=True)

    if not target.empty:
        strongest = target.sort_values("contribution_margin_ratio", ascending=False).iloc[0]
        largest_gap = target.sort_values("sales_gap", ascending=False).iloc[0]
        st.info(
            f"利益体質が最も強いのは `{strongest['name']}` で、"
            f"限界利益率は {display_percent(strongest['contribution_margin_ratio'])} です。"
            f"売上ギャップが最も大きいのは `{largest_gap['name']}` で、"
            f"{display_number(largest_gap['sales_gap'])} の差があります。"
        )


require_password()
init_state()
auto_load_latest_drive_file()

st.title("2027年9月期 事業計画シミュレーター")
if st.session_state.get("drive_loaded_notice"):
    st.success(st.session_state.pop("drive_loaded_notice"))
if st.session_state.get("drive_auto_load_error"):
    st.warning(st.session_state.pop("drive_auto_load_error"))

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
    st.session_state.use_fixed_cost_plan = st.toggle(
        "固定費計画を使う",
        value=bool(st.session_state.use_fixed_cost_plan),
        help="ONにすると、入力タブの固定費計画(年額)を使って必要売上高を逆算します。",
    )

tabs = st.tabs(["入力", "結果", "グラフ", "保存/読込"])

with tabs[0]:
    st.subheader("事業部・共通部門の実績入力")
    edited = st.data_editor(
        st.session_state.rows_editor_df,
        hide_index=True,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "type": st.column_config.SelectboxColumn("区分", options=TYPE_VALUES, required=True),
            "name": st.column_config.TextColumn("名称", required=True),
            "sales": st.column_config.TextColumn("売上", help="カンマ付きで入力できます。"),
            "cogs": st.column_config.TextColumn("売上原価", help="カンマ付きで入力できます。"),
            "variable_sga": st.column_config.TextColumn("販管費(変動)", help="カンマ付きで入力できます。"),
            "fixed_sga": st.column_config.TextColumn("販管費(固定)", help="カンマ付きで入力できます。"),
            "planned_fixed_sga": st.column_config.TextColumn("固定費計画(年額)", help="カンマ付きで入力できます。"),
            "custom_weight": st.column_config.NumberColumn("カスタム配分ウェイト", step=0.1),
        },
    )
    normalized_edited = normalize_input_editor_rows(edited)
    st.session_state.rows_df = normalized_edited
    st.session_state.rows_editor_df = input_editor_rows(normalized_edited)
    input_totals = st.session_state.rows_df.copy()
    input_total_table = pd.DataFrame(
        [
            {
                "区分": "合計",
                "名称": f"{len(input_totals)} 行",
                "売上": display_number(input_totals["sales"].sum()),
                "売上原価": display_number(input_totals["cogs"].sum()),
                "販管費(変動)": display_number(input_totals["variable_sga"].sum()),
                "販管費(固定)": display_number(input_totals["fixed_sga"].sum()),
                "固定費計画(年額)": display_number(input_totals["planned_fixed_sga"].sum()),
                "カスタム配分ウェイト": f"{input_totals['custom_weight'].sum():.1f}",
            }
        ]
    )
    st.dataframe(input_total_table, use_container_width=True, hide_index=True)
    col1, col2, col3 = st.columns([1, 1, 4])
    if col1.button("事業部を追加"):
        set_rows_state(
            pd.concat(
                [st.session_state.rows_df, pd.DataFrame([blank_row("事業部", "新規事業部")])],
                ignore_index=True,
            )
        )
        st.rerun()
    if col2.button("共通部門を追加"):
        set_rows_state(
            pd.concat(
                [st.session_state.rows_df, pd.DataFrame([blank_row("共通部門", "共通部門")])],
                ignore_index=True,
            )
        )
        st.rerun()
    if col3.button("固定費計画に今期年換算を反映"):
        rows = normalize_rows(st.session_state.rows_df)
        rows["planned_fixed_sga"] = rows["fixed_sga"] * (12 / max(st.session_state.actual_months, 1))
        set_rows_state(rows)
        st.rerun()

scenario = compute_scenario(
    st.session_state.rows_df,
    st.session_state.actual_months,
    st.session_state.goal_mode,
    st.session_state.goal_value,
    st.session_state.profit_allocation_mode,
    st.session_state.common_allocation_mode,
    st.session_state.use_fixed_cost_plan,
)

with tabs[1]:
    for warning in scenario["warnings"]:
        st.warning(warning)
    summary = scenario["summary"]
    cols = st.columns(4)
    with cols[0]:
        metric_card("全社必要売上高", summary["target_sales"])
    with cols[1]:
        metric_card("全社必要売上総利益", summary["target_gross_profit"])
    with cols[2]:
        metric_card("本部費配賦後営業利益合計", summary["target_company_op"])
        st.caption(f"利益率 {display_percent(summary['target_op_margin'])}")
    with cols[3]:
        metric_card("売上ギャップ", summary["sales_gap"])

    st.subheader("事業部別の必要予算")
    result_display_table = build_result_display_table(scenario["target"])
    st.dataframe(
        result_display_table,
        use_container_width=True,
        hide_index=True,
    )
    render_result_insights(scenario["target"], scenario["summary"])

with tabs[2]:
    render_charts(scenario["target"], scenario["summary"])

with tabs[3]:
    st.subheader("保存/読込")
    json_text = to_state_json()
    drive_tab, local_tab = st.tabs(["Google Drive", "ローカルファイル"])

    with local_tab:
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

    with drive_tab:
        if not drive_is_configured():
            error = st.session_state.pop("drive_config_error", "")
            if error:
                st.error(error)
            else:
                st.info("Google Drive連携は未設定です。Secretsに `GOOGLE_DRIVE_FOLDER_ID` とサービスアカウント情報を設定すると使えます。")
        else:
            target_ok, target_message = validate_drive_target()
            if target_ok:
                st.caption(target_message)
            else:
                st.error(target_message)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            default_name = f"business-plan-scenario_{timestamp}.json"
            drive_file_name = st.text_input("Drive保存ファイル名", value=default_name)
            if st.button("Google Driveへ保存", type="primary"):
                if not target_ok:
                    st.error("保存先がShared Driveではないため、保存を実行していません。")
                else:
                    try:
                        saved = upload_json_to_drive(drive_file_name, json_text)
                        st.success(f"Google Driveへ保存しました: {saved.get('name')}")
                        if saved.get("webViewLink"):
                            st.link_button("Google Driveで開く", saved["webViewLink"])
                    except Exception as exc:
                        st.error(f"Google Driveへの保存に失敗しました: {exc}")

            st.divider()
            if st.button("Drive上のJSON一覧を更新"):
                st.session_state.drive_files = list_drive_json_files()

            if "drive_files" not in st.session_state:
                try:
                    st.session_state.drive_files = list_drive_json_files()
                except Exception as exc:
                    st.session_state.drive_files = []
                    st.error(f"Google Driveの一覧取得に失敗しました: {exc}")

            files = st.session_state.get("drive_files", [])
            if not files:
                st.caption("保存済みJSONはまだありません。")
            else:
                labels = {
                    f"{item['name']} / 更新: {item.get('modifiedTime', '-')[:19]}": item["id"]
                    for item in files
                }
                selected_label = st.selectbox("Driveから読込むJSON", list(labels.keys()))
                if st.button("選択したJSONを読込"):
                    try:
                        payload = download_json_from_drive(labels[selected_label])
                        load_state_payload(payload)
                        st.success("Google DriveのJSONを読込みました。")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Google Driveからの読込に失敗しました: {exc}")
