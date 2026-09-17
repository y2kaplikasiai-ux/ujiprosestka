import json
import os
import re
import urllib.request
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from db_helper import get_db_connection
from excel_exporter import convert_df_to_csv_bytes

# Mapping Kode Provinsi BPS/Kemendagri ke Nama Provinsi Standard
KODE_PROVINSI_MAP = {
    "11": "ACEH",
    "12": "SUMATERA UTARA",
    "13": "SUMATERA BARAT",
    "14": "RIAU",
    "15": "JAMBI",
    "16": "SUMATERA SELATAN",
    "17": "BENGKULU",
    "18": "LAMPUNG",
    "19": "KEPULAUAN BANGKA BELITUNG",
    "21": "KEPULAUAN RIAU",
    "31": "DKI JAKARTA",
    "32": "JAWA BARAT",
    "33": "JAWA TENGAH",
    "34": "DI YOGYAKARTA",
    "35": "JAWA TIMUR",
    "36": "BANTEN",
    "51": "BALI",
    "52": "NUSA TENGGARA BARAT",
    "53": "NUSA TENGGARA TIMUR",
    "61": "KALIMANTAN BARAT",
    "62": "KALIMANTAN TENGAH",
    "63": "KALIMANTAN SELATAN",
    "64": "KALIMANTAN TIMUR",
    "65": "KALIMANTAN UTARA",
    "71": "SULAWESI UTARA",
    "72": "SULAWESI TENGAH",
    "73": "SULAWESI SELATAN",
    "74": "SULAWESI TENGGARA",
    "75": "GORONTALO",
    "76": "SULAWESI BARAT",
    "81": "MALUKU",
    "82": "MALUKU UTARA",
    "91": "PAPUA BARAT",
    "92": "PAPUA",
    "93": "PAPUA SELATAN",
    "94": "PAPUA TENGAH",
    "95": "PAPUA PEGUNUNGAN",
    "96": "PAPUA BARAT DAYA",
}


def _clean_province_name(name_str):
    """Membersihkan dan menyelaraskan penamaan provinsi secara agresif."""
    if not name_str or pd.isna(name_str):
        return "TIDAK TERDEFINISI"

    val = str(name_str).strip().upper()
    val = re.sub(
        r"^(PROVINSI|PROPINSI|PROV\.|PROV|DAERAH KHUSUS IBUKOTA|DAERAH ISTIMEWA)\s+",
        "",
        val,
    )
    val = re.sub(r"[^A-Z0-9\s]", "", val).strip()

    alias_map = {
        "D I YOGYAKARTA": "DI YOGYAKARTA",
        "DIYOGYAKARTA": "DI YOGYAKARTA",
        "DIY": "DI YOGYAKARTA",
        "YOGYAKARTA": "DI YOGYAKARTA",
        "DAERAH ISTIMEWA YOGYAKARTA": "DI YOGYAKARTA",
        "DKI": "DKI JAKARTA",
        "JAKARTA": "DKI JAKARTA",
        "DKI JAKARTA": "DKI JAKARTA",
        "JAKARTA RAYA": "DKI JAKARTA",
        "KEP BANGKA BELITUNG": "KEPULAUAN BANGKA BELITUNG",
        "BANGKA BELITUNG": "KEPULAUAN BANGKA BELITUNG",
        "KEP RIAU": "KEPULAUAN RIAU",
        "NTB": "NUSA TENGGARA BARAT",
        "NTT": "NUSA TENGGARA TIMUR",
        "IRIAN JAYA BARAT": "PAPUA BARAT",
        "IRIAN JAYA TIMUR": "PAPUA",
    }
    return alias_map.get(val, val)


def _clean_kabupaten_name(name_str):
    """Membersihkan penamaan kabupaten/kota secara agresif agar cocok dengan geojson."""
    if not name_str or pd.isna(name_str):
        return "TIDAK TERDEFINISI"
    val = str(name_str).strip().upper()
    val = re.sub(r"^(KABUPATEN|KAB\.|KAB|KOTA ADMINISTRASI|KOTA)\s+", "", val)
    val = re.sub(r"[^A-Z0-9\s]", "", val).strip()
    return val


@st.cache_data(ttl=3600, show_spinner=False)
def _load_geojson_indonesia():
    """Memuat GeoJSON Wilayah Provinsi Indonesia dengan multi-URL fallback."""
    urls = [
        "https://raw.githubusercontent.com/superpikar/indonesia-geojson/master/indonesia-province-simple.json",
        "https://raw.githubusercontent.com/ans-4175/indonesia-geojson/master/indonesia-province.geojson",
        "https://raw.githubusercontent.com/superpikar/indonesia-geojson/master/indonesia.geojson",
    ]
    for url in urls:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
                if data and "features" in data:
                    return data
        except Exception:
            continue
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def _load_geojson_kabupaten():
    """Memuat GeoJSON Wilayah Kabupaten/Kota Indonesia dengan sumber stabil."""
    urls = [
        "https://raw.githubusercontent.com/superpikar/indonesia-geojson/master/indonesia-kab-kodya.json",
        "https://raw.githubusercontent.com/ans-4175/indonesia-geojson/master/indonesia-kabupaten.geojson",
    ]
    for url in urls:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
                if data and "features" in data:
                    return data
        except Exception:
            continue
    return None


def _get_region_df(df_matrix_school, dfs):
    """Mengekstrak dan mencocokkan DataFrame Peserta dengan data Wilayah (sinkron ke df_matrix / N=276.030)."""
    df_base = st.session_state.get("df_matrix")
    if df_base is None or df_base.empty:
        df_base = df_matrix_school
    if (df_base is None or df_base.empty) and isinstance(dfs, dict) and "respon" in dfs:
        df_base = dfs["respon"]
        
    if df_base is None or df_base.empty:
        return pd.DataFrame()

    df_res = df_base.copy()
    col_user = next((c for c in df_res.columns if str(c).lower().strip() in ["username", "user_id", "id_peserta", "id"]), df_res.columns[0])
    df_res["username_clean"] = df_res[col_user].astype(str).str.strip().str.lower()
    df_res = df_res[df_res["username_clean"] != "nan"].drop_duplicates("username_clean").copy()
    
    # Ambil metadata wilayah dari DB sebagai referensi left-join (tanpa mengubah N master)
    try:
        engine = get_db_connection()
        if engine:
            df_meta = pd.read_sql("SELECT username, nama_provinsi, nama_kabupaten FROM tb_peserta_skor WHERE username IS NOT NULL AND username != ''", engine)
            if not df_meta.empty:
                df_meta["username_clean"] = df_meta["username"].astype(str).str.strip().str.lower()
                df_meta["nama_provinsi"] = df_meta["nama_provinsi"].fillna("TIDAK TERDEFINISI").apply(_clean_province_name)
                df_meta["nama_kabupaten"] = df_meta["nama_kabupaten"].fillna("TIDAK TERDEFINISI").apply(_clean_kabupaten_name)
                df_res = df_res.merge(df_meta[["username_clean", "nama_provinsi", "nama_kabupaten"]].drop_duplicates("username_clean"), on="username_clean", how="left")
                df_res["nama_provinsi"] = df_res["nama_provinsi"].fillna("TIDAK TERDEFINISI")
                df_res["nama_kabupaten"] = df_res["nama_kabupaten"].fillna("TIDAK TERDEFINISI")
                return df_res
    except Exception:
        pass
    
    col_prov = next((c for c in df_res.columns if str(c).lower().strip() in ["nama_provinsi", "provinsi", "prov", "kd_prop", "kode_provinsi"]), None)
    col_kab = next((c for c in df_res.columns if str(c).lower().strip() in ["nama_kabupaten", "kabupaten", "kota", "nama_kota"]), None)
    
    df_res["nama_provinsi"] = df_res[col_prov].apply(lambda x: _clean_province_name(KODE_PROVINSI_MAP.get(str(x).strip().upper(), str(x)))) if col_prov else "TIDAK TERDEFINISI"
    df_res["nama_kabupaten"] = df_res[col_kab].apply(_clean_kabupaten_name) if col_kab else "TIDAK TERDEFINISI"
    return df_res


def _calculate_region_stats(df_input, group_col, score_col):
    """Menghitung agregasi statistik wilayah lengkap."""
    if (
        df_input.empty
        or group_col not in df_input.columns
        or score_col not in df_input.columns
    ):
        return pd.DataFrame()

    grouped = (
        df_input.groupby(group_col)[score_col]
        .agg(
            Jumlah_Peserta="count",
            Rata_Rata="mean",
            SD="std",
            Min="min",
            Q1=lambda x: x.quantile(0.25),
            Median="median",
            Q3=lambda x: x.quantile(0.75),
            Max="max",
        )
        .reset_index()
    )

    grouped["SD"] = grouped["SD"].fillna(0.0)
    num_cols = ["Rata_Rata", "SD", "Min", "Q1", "Median", "Q3", "Max"]
    grouped[num_cols] = grouped[num_cols].round(2)

    return grouped.sort_values(by="Rata_Rata", ascending=False)


def render_tab_region(df_matrix_school, dfs):
    st.subheader("🗺️ Analisis Nilai Berbasis Wilayah & Peta Geografis")
    st.caption(
        "Memetakan sebaran nilai konversi hasil ujian, analisis kesenjangan"
        " (gap), serta visualisasi peta interaktif seluruh Indonesia."
    )

    if "selected_geo_prov" not in st.session_state:
        st.session_state.selected_geo_prov = None

    df_base = _get_region_df(df_matrix_school, dfs)
    if df_base.empty:
        st.warning(
            "⚠️ Belum ada data peserta atau informasi wilayah"
            " (Provinsi/Kabupaten) yang terdeteksi."
        )
        return

    score_columns_map = {}

    irt_results = st.session_state.get("irt_results", {})
    for m_key, m_val in irt_results.items():
        if (
            isinstance(m_val, dict)
            and "df_person" in m_val
            and not m_val["df_person"].empty
        ):
            df_p = m_val["df_person"].copy()
            u_col = next(
                (
                    c
                    for c in df_p.columns
                    if str(c).lower().strip() in ["username", "user_id", "id"]
                ),
                df_p.columns[0],
            )
            df_p["username_clean"] = (
                df_p[u_col].astype(str).str.strip().str.lower()
            )

            s_col = next(
                (
                    c
                    for c in df_p.columns
                    if str(c).lower().strip()
                    in [
                        "nilai konversi",
                        "nilai_konversi",
                        "skor_konversi",
                        "nilai_scaled",
                        "scaled_score",
                        "skor_scaled",
                    ]
                ),
                None,
            )

            if not s_col:
                num_cols = df_p.select_dtypes(include=[np.number]).columns
                for nc in num_cols:
                    if str(nc).lower().strip() not in [
                        "theta",
                        "ability",
                        "se",
                        "se_theta",
                        "se_ability",
                        "z_score",
                    ]:
                        if df_p[nc].max() > 10 or df_p[nc].min() < -5:
                            s_col = nc
                            break

            if s_col:
                label_name = f"IRT {m_key.upper()} (Skala Konversi)"
                score_columns_map[label_name] = (
                    df_p[["username_clean", s_col]]
                    .rename(columns={s_col: label_name})
                    .drop_duplicates("username_clean")
                )

    for c in df_base.columns:
        c_str = str(c).lower().strip()
        if "theta" in c_str or "ability" in c_str:
            continue

        if (
            "skor_konversi" in c_str
            or "nilai_konversi" in c_str
            or "nilai_scaled" in c_str
        ):
            name_label = f"Konversi ({c.replace('_', ' ').upper()})"
            df_temp = pd.DataFrame()
            df_temp["username_clean"] = df_base["username_clean"]
            df_temp[name_label] = pd.to_numeric(df_base[c], errors="coerce")
            score_columns_map[name_label] = df_temp.drop_duplicates(
                "username_clean"
            )
        elif (
            "skor_mentah" in c_str
            or "nilai" in c_str
            and not any(
                k in score_columns_map for k in ["Klasik / CTT (Skala 0-100)"]
            )
        ):
            vals = pd.to_numeric(df_base[c], errors="coerce")
            max_val_found = vals.max() if not vals.empty else 25.0
            if max_val_found <= 50 and max_val_found > 0:
                name_label = "Klasik / CTT (Skala 0-100)"
                df_temp = pd.DataFrame()
                df_temp["username_clean"] = df_base["username_clean"]
                df_temp[name_label] = (vals / max_val_found) * 100.0
                score_columns_map[name_label] = df_temp.drop_duplicates(
                    "username_clean"
                )

    if "Klasik / CTT (Skala 0-100)" not in score_columns_map:
        for c in df_base.columns:
            if "skor" in str(c).lower() or "nilai" in str(c).lower():
                vals = pd.to_numeric(df_base[c], errors="coerce")
                if not vals.dropna().empty:
                    m_val = vals.max()
                    name_label = "Klasik / CTT (Skala 0-100)"
                    df_temp = pd.DataFrame()
                    df_temp["username_clean"] = df_base["username_clean"]
                    df_temp[name_label] = (
                        (vals / m_val) * 100.0 if m_val > 0 else vals
                    )
                    score_columns_map[name_label] = df_temp.drop_duplicates(
                        "username_clean"
                    )
                    break

    if not score_columns_map:
        st.info(
            "💡 Belum ada data nilai konversi yang tersedia. Silakan jalankan"
            " **Scoring Engine** atau **Analisis IRT** terlebih dahulu."
        )
        return

    col_sel1, _ = st.columns(2)
    with col_sel1:
        sorted_opt_keys = sorted(
            list(score_columns_map.keys()),
            key=lambda x: 0 if "KLASIK" in x.upper() or "CTT" in x.upper() else 1,
        )
        selected_score_label = st.selectbox(
            "🎯 Pilih Metode Skor Konversi:",
            options=sorted_opt_keys,
            index=0,
            help=(
                "Pilih model nilai konversi (skala 0-100) yang akan dianalisis"
                " distribusinya secara geografis."
            ),
        )

    df_score_selected = score_columns_map[selected_score_label].copy()
    val_col_name = selected_score_label

    df_merged = df_base.merge(
        df_score_selected, on="username_clean", how="inner"
    )
    df_merged[val_col_name] = pd.to_numeric(
        df_merged[val_col_name], errors="coerce"
    )
    df_merged = df_merged.dropna(subset=[val_col_name])

    if df_merged.empty:
        st.error(
            "❌ Tidak dapat mengaitkan data skor peserta dengan data wilayah."
        )
        return

    st.divider()

    st.markdown("### 🇮🇩 1. Ringkasan & Kesenjangan (Gap) Statistik Nasional")

    avg_nat = df_merged[val_col_name].mean()
    total_peserta = len(df_merged)

    stats_prov = _calculate_region_stats(
        df_merged, "nama_provinsi", val_col_name
    )

    if not stats_prov.empty:
        std_val = df_merged[val_col_name].std()
        top_prov = stats_prov.iloc[0]
        bot_prov = stats_prov.iloc[-1]
        disparitas_val = top_prov["Rata_Rata"] - bot_prov["Rata_Rata"]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric(
            "Total Peserta Terjangkau", f"{total_peserta:,}".replace(",", ".")
        )
        m2.metric("Rata-Rata Nasional (Konversi)", f"{avg_nat:.2f}")
        m3.metric("Standar Deviasi", f"{std_val:.2f}")
        m4.metric(
            "Disparitas",
            f"{disparitas_val:.2f} Poin",
            delta=(
                f"Tertinggi: {top_prov['Rata_Rata']:.2f} | "
                f"Terendah: {bot_prov['Rata_Rata']:.2f}"
            ),
            delta_color="off",
        )

    st.divider()

    st.markdown("### 🗺️ 2. Peta Interaktif Sebaran Nilai (Provinsi & Kabupaten)")

    prov_list = sorted(list(df_merged["nama_provinsi"].unique()))
    col_nav1, col_nav2 = st.columns(2)

    with col_nav1:
        selected_prov_view = st.selectbox(
            "🔎 Pilih Provinsi untuk Drill-Down Detail Kabupaten/Kota (atau"
            " Pilih Nasional):",
            options=["-- TAMPILKAN SELURUH INDONESIA (PROVINSI) --"] + prov_list,
            index=0
            if not st.session_state.selected_geo_prov
            else (
                prov_list.index(st.session_state.selected_geo_prov) + 1
                if st.session_state.selected_geo_prov in prov_list
                else 0
            ),
        )

    with col_nav2:
        st.write("")
        st.write("")
        if st.button("🔄 Reset ke Peta Nasional", use_container_width=True):
            st.session_state.selected_geo_prov = None
            st.rerun()

    if selected_prov_view != "-- TAMPILKAN SELURUH INDONESIA (PROVINSI) --":
        st.session_state.selected_geo_prov = selected_prov_view
    else:
        st.session_state.selected_geo_prov = None

    custom_red_to_blue = ["red", "yellow", "blue"]

    if st.session_state.selected_geo_prov is None:
        geojson_id = _load_geojson_indonesia()

        if not stats_prov.empty and geojson_id:
            for feature in geojson_id.get("features", []):
                props = feature.get("properties", {})
                found_name = None
                for k_prop in [
                    "state",
                    "NAME_1",
                    "Propinsi",
                    "provinsi",
                    "name",
                    "NAME_0",
                    "PROVINSI",
                    "name_province",
                    "nama",
                ]:
                    if k_prop in props and props[k_prop]:
                        found_name = props[k_prop]
                        break
                feature["properties"]["norm_name"] = _clean_province_name(
                    found_name
                )

            stats_prov["Provinsi_Clean"] = stats_prov["nama_provinsi"].apply(
                _clean_province_name
            )

            valid_scores = stats_prov["Rata_Rata"].dropna()
            min_val = (
                float(valid_scores.min()) if not valid_scores.empty else 0.0
            )
            max_val = (
                float(valid_scores.max()) if not valid_scores.empty else 100.0
            )
            if max_val - min_val < 0.01:
                min_val -= 1.0
                max_val += 1.0

            fig_map = px.choropleth(
                stats_prov,
                geojson=geojson_id,
                locations="Provinsi_Clean",
                featureidkey="properties.norm_name",
                color="Rata_Rata",
                color_continuous_scale=custom_red_to_blue,
                range_color=(min_val, max_val),
                labels={
                    "Rata_Rata": "Rata-Rata Skor",
                    "Provinsi_Clean": "Provinsi",
                },
                hover_data={
                    "Jumlah_Peserta": ":,.0f",
                    "Rata_Rata": ":.2f",
                    "Min": ":.2f",
                    "Max": ":.2f",
                },
                title=(
                    f"<b>Peta Wilayah Nilai {selected_score_label} per"
                    " Provinsi</b>"
                ),
            )

            fig_map.update_traces(
                marker_line_color="#ffffff", marker_line_width=1.8
            )

            fig_map.update_geos(
                fitbounds="locations",
                visible=False,
                showcoastlines=True,
                coastlinecolor="#ffffff",
                coastlinewidth=1.2,
                showsubunits=True,
                subunitcolor="#ffffff",
                subunitwidth=1.8,
                showland=True,
                landcolor="#1c212c",
                showocean=True,
                oceancolor="#0e1117",
            )

            fig_map.update_layout(
                margin={"r": 0, "t": 40, "l": 0, "b": 0},
                paper_bgcolor="#0e1117",
                plot_bgcolor="#0e1117",
                font_color="#ffffff",
                height=550,
            )

            st.plotly_chart(fig_map, use_container_width=True)
        else:
            st.warning(
                "⚠️ Gagal memuat data GeoJSON batas provinsi Indonesia."
            )

    else:
        target_prov = st.session_state.selected_geo_prov
        st.info(
            f"📍 **Peta Detail Kabupaten/Kota di Provinsi {target_prov}**"
        )

        df_prov_kab = df_merged[df_merged["nama_provinsi"] == target_prov]
        stats_kab_local = _calculate_region_stats(
            df_prov_kab, "nama_kabupaten", val_col_name
        )

        geojson_kab = _load_geojson_kabupaten()

        if not stats_kab_local.empty and geojson_kab:
            for feature in geojson_kab.get("features", []):
                props = feature.get("properties", {})
                found_kab = None
                for k_prop in [
                    "kabkota",
                    "KABKOT",
                    "NAME_2",
                    "kabupaten",
                    "name",
                    "NAME_1",
                    "KABUPATEN",
                    "kota",
                ]:
                    if k_prop in props and props[k_prop]:
                        found_kab = props[k_prop]
                        break
                feature["properties"]["norm_kab"] = _clean_kabupaten_name(
                    found_kab
                )

            stats_kab_local["Kabupaten_Clean"] = stats_kab_local[
                "nama_kabupaten"
            ].apply(_clean_kabupaten_name)

            v_scores = stats_kab_local["Rata_Rata"].dropna()
            min_k = float(v_scores.min()) if not v_scores.empty else 0.0
            max_k = float(v_scores.max()) if not v_scores.empty else 100.0

            if max_k - min_k < 0.01:
                min_k -= 1.0
                max_k += 1.0

            fig_kab_map = px.choropleth(
                stats_kab_local,
                geojson=geojson_kab,
                locations="Kabupaten_Clean",
                featureidkey="properties.norm_kab",
                color="Rata_Rata",
                color_continuous_scale=custom_red_to_blue,
                range_color=(min_k, max_k),
                labels={
                    "Rata_Rata": "Rata-Rata Skor",
                    "Kabupaten_Clean": "Kabupaten / Kota",
                },
                hover_data={
                    "Jumlah_Peserta": ":,.0f",
                    "Rata_Rata": ":.2f",
                    "Min": ":.2f",
                    "Max": ":.2f",
                },
                title=(
                    f"<b>Sebaran Nilai Kabupaten/Kota di Provinsi"
                    f" {target_prov}</b>"
                ),
            )

            fig_kab_map.update_traces(
                marker_line_color="#ffffff", marker_line_width=1.5
            )

            fig_kab_map.update_geos(
                fitbounds="locations",
                visible=False,
                showcoastlines=True,
                coastlinecolor="#ffffff",
                coastlinewidth=1.2,
                showsubunits=True,
                subunitcolor="#ffffff",
                subunitwidth=1.5,
                showland=True,
                landcolor="#1c212c",
                showocean=True,
                oceancolor="#0e1117",
            )

            fig_kab_map.update_layout(
                margin={"r": 0, "t": 40, "l": 0, "b": 0},
                paper_bgcolor="#0e1117",
                plot_bgcolor="#0e1117",
                font_color="#ffffff",
                height=550,
            )

            st.plotly_chart(fig_kab_map, use_container_width=True)
        else:
            st.warning(
                "⚠️ Data GeoJSON Kabupaten/Kota atau data rekap kabupaten"
                f" untuk provinsi **{target_prov}** belum lengkap."
            )

    st.divider()

    st.markdown("### 🏛️ 3. Grafik & Peringkat per Provinsi")

    fig_prov = px.bar(
        stats_prov,
        x="nama_provinsi",
        y="Rata_Rata",
        color="Rata_Rata",
        color_continuous_scale=custom_red_to_blue,
        text_auto=".1f",
        title=(
            "<b>Rata-Rata Nilai Konversi"
            f" ({selected_score_label}) per Provinsi</b>"
        ),
        labels={"Rata_Rata": "Rata-Rata Nilai", "nama_provinsi": "Provinsi"},
    )
    fig_prov.add_hline(
        y=avg_nat,
        line_dash="dash",
        line_color="red",
        annotation_text=f"Rata-rata Nasional ({avg_nat:.2f})",
        annotation_position="top right",
    )
    fig_prov.update_layout(
        template="plotly_dark",
        height=450,
        xaxis_tickangle=-45,
        paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117",
    )
    st.plotly_chart(fig_prov, use_container_width=True)

    with st.expander(
        "📋 Tabel Agregasi Statistik Tingkat Provinsi", expanded=False
    ):
        st.dataframe(
            stats_prov.drop(columns=["Provinsi_Clean"], errors="ignore"),
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    st.markdown("### 🏙️ 4. Analisis Tingkat Kabupaten / Kota")

    tab_kab1, tab_kab2 = st.tabs(
        [
            "📌 Filter Berdasarkan Provinsi",
            "🌐 Peringkat Kabupaten/Kota Nasional",
        ]
    )

    with tab_kab1:
        list_prov = sorted(df_merged["nama_provinsi"].unique())
        selected_prov = st.selectbox(
            "Pilih Provinsi untuk Detail Kabupaten/Kota:", options=list_prov
        )

        df_sub_kab = df_merged[df_merged["nama_provinsi"] == selected_prov]
        stats_kab_sub = _calculate_region_stats(
            df_sub_kab, "nama_kabupaten", val_col_name
        )

        if not stats_kab_sub.empty:
            avg_sub_prov = df_sub_kab[val_col_name].mean()

            fig_kab_sub = px.bar(
                stats_kab_sub,
                x="nama_kabupaten",
                y="Rata_Rata",
                color="Rata_Rata",
                color_continuous_scale=custom_red_to_blue,
                text_auto=".1f",
                title=(
                    "<b>Rata-Rata Nilai Konversi Kabupaten/Kota di"
                    f" {selected_prov}</b>"
                ),
                labels={
                    "Rata_Rata": "Rata-Rata Nilai",
                    "nama_kabupaten": "Kabupaten / Kota",
                },
            )
            fig_kab_sub.add_hline(
                y=avg_sub_prov,
                line_dash="dash",
                line_color="yellow",
                annotation_text=f"Rata-rata Provinsi ({avg_sub_prov:.2f})",
            )
            fig_kab_sub.update_layout(
                template="plotly_dark",
                height=420,
                xaxis_tickangle=-45,
                paper_bgcolor="#0e1117",
                plot_bgcolor="#0e1117",
            )
            st.plotly_chart(fig_kab_sub, use_container_width=True)

            st.dataframe(
                stats_kab_sub, use_container_width=True, hide_index=True
            )

    with tab_kab2:
        stats_kab_nat = _calculate_region_stats(
            df_merged, "nama_kabupaten", val_col_name
        )

        st.caption("Menampilkan 30 Kabupaten/Kota dengan capaian tertinggi:")
        fig_kab_nat = px.bar(
            stats_kab_nat.head(30),
            x="nama_kabupaten",
            y="Rata_Rata",
            color="Rata_Rata",
            color_continuous_scale=custom_red_to_blue,
            text_auto=".1f",
            title="<b>Top 30 Kabupaten/Kota Tertinggi se-Indonesia</b>",
            labels={
                "Rata_Rata": "Rata-Rata Nilai",
                "nama_kabupaten": "Kabupaten / Kota",
            },
        )
        fig_kab_nat.update_layout(
            template="plotly_dark",
            height=450,
            xaxis_tickangle=-45,
            paper_bgcolor="#0e1117",
            plot_bgcolor="#0e1117",
        )
        st.plotly_chart(fig_kab_nat, use_container_width=True)

        with st.expander(
            "📋 Seluruh Data Agregasi Kabupaten/Kota se-Indonesia",
            expanded=False,
        ):
            st.dataframe(
                stats_kab_nat, use_container_width=True, hide_index=True
            )

    st.divider()

    st.markdown("### 💾 Unduh Laporan Wilayah")
    c_dl1, c_dl2 = st.columns(2)
    with c_dl1:
        csv_prov = convert_df_to_csv_bytes(
            stats_prov.drop(columns=["Provinsi_Clean"], errors="ignore")
        )
        st.download_button(
            "📄 Unduh CSV Statistik Provinsi",
            data=csv_prov,
            file_name=(
                "Statistik_Wilayah_Provinsi_"
                f"{selected_score_label.replace(' ', '_')}.csv"
            ),
            mime="text/csv",
            use_container_width=True,
        )
    with c_dl2:
        stats_kab_all = _calculate_region_stats(
            df_merged, "nama_kabupaten", val_col_name
        )
        csv_kab = convert_df_to_csv_bytes(stats_kab_all)
        st.download_button(
            "📄 Unduh CSV Statistik Kabupaten/Kota",
            data=csv_kab,
            file_name=(
                "Statistik_Wilayah_Kabupaten_"
                f"{selected_score_label.replace(' ', '_')}.csv"
            ),
            mime="text/csv",
            use_container_width=True,
        )