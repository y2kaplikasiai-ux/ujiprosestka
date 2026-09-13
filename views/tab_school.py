# views/tab_school.py
import pandas as pd
import plotly.express as px
import streamlit as st
from db_helper import get_db_connection
from excel_exporter import convert_df_to_csv_bytes


@st.cache_data(ttl=60)
def load_data_from_mysql():
    """
    Membaca seluruh data peserta dan skor langsung dari MySQL Server secara efisien.
    """
    try:
        engine = get_db_connection()
        if engine is None:
            return None
        query = "SELECT * FROM tb_peserta_skor"
        df = pd.read_sql_query(query, con=engine)
        return df
    except Exception as e:
        st.warning(f"⚠️ Gagal terhubung ke MySQL Server: {e}. Menggunakan data lokal session state.")
        return None


def render_tab_school(df_matrix_school, dfs=None, irt_results=None):
    st.subheader("🏫 Hasil Analisis Statistik Per Sekolah")

    # --- 1. AMBIL DATA (MYSQL UTAMA -> FALLBACK SESSION) ---
    df_db = load_data_from_mysql()

    if df_db is not None and not df_db.empty:
        df_master = df_db.copy()
        is_from_mysql = True
    elif df_matrix_school is not None and not df_matrix_school.empty:
        # OPTIMASI MEMORI: Hanya ambil kolom esensial/metadata dan skor untuk menghindari ArrayMemoryError
        essential_cols = [
            c for c in df_matrix_school.columns 
            if c in [
                "username", "user_id", "id_peserta", "nama", "nama_sekolah", "_school_key", 
                "nama_kabupaten", "nama_provinsi", "kd_prop", "kode_provinsi", "skor_mentah", 
                "Jumlah_Soal", "skor_konversi_ctt", "skor_konversi_rasch", 
                "skor_konversi_1pl", "skor_konversi_2pl", "skor_konversi_3pl"
            ]
        ]
        if not essential_cols:
            essential_cols = list(df_matrix_school.columns[:30])
        
        df_master = df_matrix_school[essential_cols].copy()
        is_from_mysql = False
    else:
        st.info(
            "💡 **Informasi:** Berkas **Master Sekolah** (`sekolah`) belum diunggah atau "
            "data peserta belum diproses ke database MySQL."
        )
        return

    # --- 2. DETEKSI METODE NILAI KONVERSI ---
    available_methods = {}

    if is_from_mysql:
        # Kolom dari Database MySQL
        if "skor_konversi_ctt" in df_master.columns and df_master["skor_konversi_ctt"].notna().any():
            available_methods["Nilai Konversi (Klasik/CTT)"] = "skor_konversi_ctt"
        if "skor_konversi_rasch" in df_master.columns and df_master["skor_konversi_rasch"].notna().any():
            available_methods["Nilai Konversi (IRT - Rasch/1PL)"] = "skor_konversi_rasch"
        if "skor_konversi_2pl" in df_master.columns and df_master["skor_konversi_2pl"].notna().any():
            available_methods["Nilai Konversi (IRT - 2PL)"] = "skor_konversi_2pl"
        if "skor_konversi_3pl" in df_master.columns and df_master["skor_konversi_3pl"].notna().any():
            available_methods["Nilai Konversi (IRT - 3PL)"] = "skor_konversi_3pl"
    else:
        # Fallback dari Dataframe Memori
        if "Nilai_Konversi" in df_master.columns:
            available_methods["Nilai Konversi (Klasik/CTT)"] = "Nilai_Konversi"
        elif "skor_mentah" in df_master.columns:
            available_methods["Skor Mentah (Klasik/CTT)"] = "skor_mentah"

        if irt_results is None or not irt_results:
            irt_results = st.session_state.get("irt_results", {})

        def extract_irt_scores(df_person):
            for col in ["Nilai_Scaled", "scale_score", "nilai_konversi", "Nilai_Konversi", "skor_skala", "scale", "theta"]:
                if col in df_person.columns:
                    return df_person[col].values
            return None

        if irt_results and isinstance(irt_results, dict):
            for key_model, label_model, col_name in [
                ("rasch", "Nilai Konversi (IRT - Rasch/1PL)", "Konversi_Rasch"),
                ("2pl", "Nilai Konversi (IRT - 2PL)", "Konversi_2PL"),
                ("3pl", "Nilai Konversi (IRT - 3PL)", "Konversi_3PL"),
            ]:
                if key_model in irt_results and isinstance(irt_results[key_model], dict):
                    df_p = irt_results[key_model].get("df_person")
                    if df_p is not None and not df_p.empty:
                        scores = extract_irt_scores(df_p)
                        if scores is not None and len(scores) == len(df_master):
                            df_master[col_name] = scores
                            available_methods[label_model] = col_name

    if not available_methods:
        st.error("❌ Tidak ditemukan kolom nilai konversi yang dapat dianalisis.")
        return

    # --- 3. PILIHAN METODE ANALISIS ---
    st.markdown("#### ⚙️ Pengaturan Metode Analisis")
    selected_method_label = st.radio(
        "Pilih Metode & Metrik Nilai yang Ingin Dianalisis:",
        options=list(available_methods.keys()),
        horizontal=True,
        key="radio_sekolah_method",
    )
    selected_metric_col = available_methods[selected_method_label]

    st.divider()

    # --- 4. FILTER WILAYAH & JUMLAH PESERTA ---
    st.markdown("#### 🔍 Filter Wilayah & Jumlah Peserta")
    col_f1, col_f2 = st.columns([3, 1])

    prov_dict = {}

    def clean_str(val):
        if pd.isna(val):
            return ""
        return str(val).strip().rstrip(",").strip()

    # Ekstraksi Daftar Provinsi
    if "kode_provinsi" in df_master.columns and "nama_provinsi" in df_master.columns:
        df_prov_pairs = df_master[["kode_provinsi", "nama_provinsi"]].dropna().drop_duplicates()
        for _, row in df_prov_pairs.iterrows():
            kd_str = clean_str(row["kode_provinsi"]).replace(".0", "").zfill(2)
            nm_str = clean_str(row["nama_provinsi"]).upper()
            if kd_str and nm_str:
                prov_dict[kd_str] = nm_str
    elif "kd_prop" in df_master.columns and "nama_provinsi" in df_master.columns:
        df_prov_pairs = df_master[["kd_prop", "nama_provinsi"]].dropna().drop_duplicates()
        for _, row in df_prov_pairs.iterrows():
            kd_str = clean_str(row["kd_prop"]).replace(".0", "").zfill(2)
            nm_str = clean_str(row["nama_provinsi"]).upper()
            if kd_str and nm_str:
                prov_dict[kd_str] = nm_str

    prov_options = [f"{k} - {v}" for k, v in sorted(prov_dict.items())]

    with col_f1:
        selected_prov_options = st.multiselect(
            "Filter Berdasarkan Provinsi (Kode - Nama Provinsi):",
            options=prov_options,
            default=[],
            key="filter_provinsi_single",
            placeholder="Semua Provinsi",
        )

    with col_f2:
        min_peserta = st.number_input(
            "Minimal Jumlah Peserta:",
            min_value=1,
            value=1,
            step=1,
            key="filter_min_peserta",
            help="Tampilkan hanya sekolah yang memiliki jumlah peserta minimal sejumlah angka ini.",
        )

    df_filtered_school = df_master.copy()

    # Penerapan Filter Provinsi
    if selected_prov_options:
        selected_codes = [opt.split(" - ")[0].strip() for opt in selected_prov_options]
        col_prov_kd = "kode_provinsi" if "kode_provinsi" in df_filtered_school.columns else "kd_prop"

        df_filtered_school["_kd_prop_clean"] = (
            df_filtered_school[col_prov_kd]
            .astype(str)
            .str.strip()
            .str.replace(".0", "", regex=False)
            .str.rstrip(",")
            .str.zfill(2)
        )
        df_filtered_school = df_filtered_school[
            df_filtered_school["_kd_prop_clean"].isin(selected_codes)
        ]

    if df_filtered_school.empty:
        st.warning("⚠️ Tidak ada data sekolah yang memenuhi kriteria filter provinsi yang dipilih.")
        return

    # --- 5. AGREGASI DATA PER SEKOLAH ---
    id_user_col = "id_peserta" if "id_peserta" in df_filtered_school.columns else df_filtered_school.columns[0]

    col_sek_kd = "kode_sekolah" if "kode_sekolah" in df_filtered_school.columns else "_school_key"
    group_cols = [col_sek_kd, "nama_sekolah"]

    if "nama_kabupaten" in df_filtered_school.columns:
        group_cols.append("nama_kabupaten")
    if "nama_provinsi" in df_filtered_school.columns:
        group_cols.append("nama_provinsi")

    # Mengabaikan nilai NULL saat melakukan agregasi rata-rata
    df_valid_scores = df_filtered_school.dropna(subset=[selected_metric_col])

    if df_valid_scores.empty:
        st.warning("⚠️ Tidak ada data nilai yang valid untuk metode yang dipilih.")
        return

    df_school_summary = (
        df_valid_scores.groupby(group_cols, as_index=False)
        .agg(
            Jumlah_Peserta=(id_user_col, "count"),
            Rata_Rata=(selected_metric_col, "mean"),
            Nilai_Min=(selected_metric_col, "min"),
            Nilai_Max=(selected_metric_col, "max"),
            Std_Deviasi=(selected_metric_col, "std"),
        )
    )

    df_school_summary = df_school_summary[
        df_school_summary["Jumlah_Peserta"] >= min_peserta
    ].copy()

    if df_school_summary.empty:
        st.warning(f"⚠️ Tidak ada sekolah yang memiliki jumlah peserta minimal {min_peserta}.")
        return

    rename_dict = {
        col_sek_kd: "Kode_Sekolah",
        "nama_sekolah": "Nama_Sekolah",
        "nama_kabupaten": "Nama_Kabupaten",
        "nama_provinsi": "Nama_Provinsi",
        "Rata_Rata": "Rata_Nilai_Konversi",
    }
    df_school_summary.rename(columns=rename_dict, inplace=True)
    mean_col_name = "Rata_Nilai_Konversi"

    df_school_summary = df_school_summary.round(2)
    df_school_summary["Std_Deviasi"] = df_school_summary["Std_Deviasi"].fillna(0.0)

    # --- 6. KPI METRICS ---
    st.divider()
    s_c1, s_c2, s_c3, s_c4 = st.columns(4)
    s_c1.metric("Total Sekolah Terdata", f"{len(df_school_summary):,}")
    s_c2.metric("Total Peserta Terfilter", f"{df_school_summary['Jumlah_Peserta'].sum():,}")
    s_c3.metric(
        "Rata-rata Konversi Tertinggi",
        f"{df_school_summary[mean_col_name].max():.2f}",
    )
    s_c4.metric(
        "Rata-rata Konversi Terendah",
        f"{df_school_summary[mean_col_name].min():.2f}",
    )
    st.divider()

    # --- 7. GRAFIK BAR CHART ---
    top_schools = df_school_summary.sort_values(
        by=mean_col_name, ascending=True
    ).tail(15)

    hover_cols = [c for c in ["Nama_Provinsi", "Nama_Kabupaten", "Jumlah_Peserta"] if c in top_schools.columns]

    fig_school_bar = px.bar(
        top_schools,
        x=mean_col_name,
        y="Nama_Sekolah",
        orientation="h",
        text=mean_col_name,
        title=f"<b>15 Sekolah Teratas Berdasarkan {selected_method_label}</b>",
        labels={
            mean_col_name: f"Rata-rata ({selected_method_label})",
            "Nama_Sekolah": "Nama Sekolah",
        },
        color=mean_col_name,
        color_continuous_scale="Blues",
        hover_data=hover_cols,
    )

    fig_school_bar.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis_title=f"<b>Rata-rata {selected_method_label}</b>",
        yaxis_title="<b>Sekolah</b>",
        margin=dict(l=20, r=20, t=50, b=40),
    )

    st.plotly_chart(fig_school_bar, use_container_width=True)
    st.divider()

    # --- 8. TABEL RINCIAN & EKSPOR CSV ---
    st.markdown("#### 📋 Tabel Rincian Ringkasan Per Sekolah")

    df_school_display = df_school_summary.sort_values(
        by=mean_col_name, ascending=False
    ).copy()

    cols_order = [
        "Kode_Sekolah",
        "Nama_Sekolah",
        "Nama_Kabupaten",
        "Nama_Provinsi",
        "Jumlah_Peserta",
        mean_col_name,
        "Nilai_Min",
        "Nilai_Max",
        "Std_Deviasi",
    ]
    cols_order = [c for c in cols_order if c in df_school_display.columns]
    df_school_display = df_school_display[cols_order]

    if "No." not in df_school_display.columns:
        df_school_display.insert(0, "No.", range(1, 1 + len(df_school_display)))

    st.dataframe(df_school_display, use_container_width=True, hide_index=True)

    csv_school_bytes = convert_df_to_csv_bytes(df_school_display)
    st.download_button(
        label="📥 Download Ringkasan Rekap Per Sekolah (.csv)",
        data=csv_school_bytes,
        file_name="Rekap_Analisis_Hasil_Per_Sekolah.csv",
        mime="text/csv",
        type="primary",
        key="btn_dl_school_csv",
    )