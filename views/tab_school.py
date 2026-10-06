# views/tab_school.py
import pandas as pd
import plotly.express as px
import streamlit as st
from db_helper import get_db_connection
from excel_exporter import convert_df_to_csv_bytes
from validators import get_mapel_lookup_dict


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
        
        # Normalisasi otomatis nama kolom jika ada variasi penamaan di database
        col_mappings = {
            "sekolah": "nama_sekolah",
            "nama_lembaga": "nama_sekolah",
            "npsn": "kode_sekolah",
            "kabupaten": "nama_kabupaten",
            "provinsi": "nama_provinsi",
        }
        for old_col, new_col in col_mappings.items():
            if old_col in df.columns and new_col not in df.columns:
                df[new_col] = df[old_col]

        return df
    except Exception as e:
        st.warning(f"⚠️ Gagal terhubung ke MySQL Server: {e}. Menggunakan data lokal session state.")
        return None


def render_tab_school(df_matrix_school, dfs=None, irt_results=None):
    st.subheader("🏫 Hasil Analisis Statistik Per Sekolah")

    # --- JALUR CEPAT: PRA-KOMPUTASI INSTAN (HANYA ~36k BARIS, BUKAN 3.34 JUTA BARIS) ---
    df_cached_comp = st.session_state.get("df_school_composite")
    df_cached_m = st.session_state.get("df_school_by_mapel")

    if df_cached_comp is not None and not df_cached_comp.empty:
        # 1. Pilihan Mata Pelajaran
        available_mapels = []
        if df_cached_m is not None and not df_cached_m.empty and "mapel" in df_cached_m.columns:
            available_mapels = sorted([
                str(m).strip() for m in df_cached_m["mapel"].dropna().unique()
                if str(m).strip() not in ["", "nan", "None", "-"]
            ])

        selected_mapels = []
        if available_mapels:
            st.markdown("#### 📚 Filter & Penggabungan Mata Pelajaran")
            selected_mapels = st.multiselect(
                "Pilih Mata Pelajaran (Bisa memilih lebih dari 1 untuk analisis gabungan):",
                options=available_mapels,
                default=available_mapels,
                key="filter_school_mapel_multi",
                help="Pilih 1 atau beberapa mata pelajaran. Jika memilih lebih dari 1 mata pelajaran, nilai dihitung dari rata-rata gabungan."
            )
            if not selected_mapels:
                st.warning("⚠️ Silakan pilih setidaknya satu mata pelajaran untuk dianalisis.")
                return

            if len(selected_mapels) > 1:
                st.info(f"✨ **Analisis Gabungan ({len(selected_mapels)} Mapel):** {', '.join(selected_mapels)}. Rerata nilai sekolah dihitung dari gabungan nilai siswa.")
            else:
                st.caption(f"📌 **Mata Pelajaran Aktif:** {selected_mapels[0]}")

        # 2. Pilihan Metode
        available_methods = {}
        if "skor_konversi_ctt" in df_cached_comp.columns:
            available_methods["Nilai Konversi (Klasik/CTT)"] = "skor_konversi_ctt"
        if "skor_konversi_rasch" in df_cached_comp.columns:
            available_methods["Nilai Konversi (IRT - Rasch/1PL)"] = "skor_konversi_rasch"
        if "skor_konversi_2pl" in df_cached_comp.columns:
            available_methods["Nilai Konversi (IRT - 2PL)"] = "skor_konversi_2pl"
        if "skor_konversi_3pl" in df_cached_comp.columns:
            available_methods["Nilai Konversi (IRT - 3PL)"] = "skor_konversi_3pl"
        if not available_methods and "skor_mentah" in df_cached_comp.columns:
            available_methods["Skor Mentah (Klasik/CTT)"] = "skor_mentah"

        if not available_methods:
            st.error("❌ Tidak ditemukan kolom nilai konversi yang dapat dianalisis.")
            return

        st.markdown("#### ⚙️ Pengaturan Metode Analisis")
        selected_method_label = st.radio(
            "Pilih Metode & Metrik Nilai yang Ingin Dianalisis:",
            options=list(available_methods.keys()),
            horizontal=True,
            key="radio_sekolah_method",
        )
        selected_metric_col = available_methods[selected_method_label]
        st.divider()

        # 3. Filter Wilayah & Jumlah Peserta
        st.markdown("#### 🔍 Filter Wilayah & Jumlah Peserta")
        col_f1, col_f2 = st.columns(2)

        prov_dict = {}
        df_prov_pairs = df_cached_comp[["kode_provinsi", "nama_provinsi"]].dropna().drop_duplicates()
        for _, row in df_prov_pairs.iterrows():
            kd_raw = str(row["kode_provinsi"]).strip()
            if kd_raw in ["-", "", "nan"]:
                continue
            kd_str = kd_raw.replace(".0", "").zfill(2)
            nm_str = str(row["nama_provinsi"]).strip().upper()
            if nm_str and nm_str not in ["-", "NAN"]:
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

        # 4. Agregasi Cepat Sub-Milidetik
        if not available_mapels or len(selected_mapels) == len(available_mapels):
            df_base_sch = df_cached_comp.copy()
        elif len(selected_mapels) == 1 and df_cached_m is not None and not df_cached_m.empty and selected_metric_col in df_cached_m.columns:
            df_base_sch = df_cached_m[df_cached_m["mapel"] == selected_mapels[0]].copy()
        elif df_cached_m is not None and not df_cached_m.empty and selected_metric_col in df_cached_m.columns:
            df_sub_m = df_cached_m[df_cached_m["mapel"].isin(selected_mapels)]
            df_base_sch = df_sub_m.groupby(["kode_sekolah", "nama_sekolah", "nama_kabupaten", "nama_provinsi", "kode_provinsi"], as_index=False).agg({
                "jumlah_peserta": "sum",
                selected_metric_col: "mean"
            })
        else:
            df_base_sch = df_cached_comp.copy()

        if selected_prov_options:
            selected_codes = [opt.split(" - ")[0].strip() for opt in selected_prov_options]
            df_base_sch["_kd_prop_clean"] = df_base_sch["kode_provinsi"].astype(str).str.strip().str.replace(".0", "", regex=False).str.zfill(2)
            df_base_sch = df_base_sch[df_base_sch["_kd_prop_clean"].isin(selected_codes)]

        df_base_sch["Jumlah_Peserta"] = pd.to_numeric(df_base_sch.get("jumlah_peserta", df_base_sch.get("Jumlah_Peserta", 0)), errors="coerce").fillna(0).astype(int)
        df_base_sch = df_base_sch[df_base_sch["Jumlah_Peserta"] >= min_peserta].copy()

        df_school_summary = pd.DataFrame()
        df_school_summary["kode_sekolah"] = df_base_sch["kode_sekolah"]
        df_school_summary["nama_sekolah"] = df_base_sch["nama_sekolah"]
        df_school_summary["nama_kabupaten"] = df_base_sch["nama_kabupaten"]
        df_school_summary["nama_provinsi"] = df_base_sch["nama_provinsi"]
        df_school_summary["Jumlah_Peserta"] = df_base_sch["Jumlah_Peserta"]
        df_school_summary["Rata_Rata"] = pd.to_numeric(df_base_sch[selected_metric_col], errors="coerce").round(2)
        df_school_summary["Nilai_Min"] = df_school_summary["Rata_Rata"]
        df_school_summary["Nilai_Max"] = df_school_summary["Rata_Rata"]
        df_school_summary["Std_Deviasi"] = 0.0
        col_sek_kd = "kode_sekolah"

    else:
        # --- JALUR CADANGAN: AMBIL DATA LENGKAP JIKA CACHE BELUM ADA ---
        df_master = None
        cand_df = st.session_state.get("df_peserta_skor")
        if cand_df is None or cand_df.empty:
            cand_df = df_matrix_school if (df_matrix_school is not None and not df_matrix_school.empty) else None

        if cand_df is not None and not cand_df.empty:
            has_sch = any(c in cand_df.columns for c in ["nama_sekolah", "sekolah", "nama_lembaga", "kode_sekolah", "npsn", "_school_key"])
            has_score = any(c in cand_df.columns for c in ["skor_konversi_ctt", "skor_mentah", "skor_konversi_rasch"])
            if has_sch and has_score:
                df_master = cand_df.copy()

        if df_master is None or df_master.empty:
            df_db = load_data_from_mysql()
            if df_db is not None and not df_db.empty:
                df_master = df_db.copy()
            else:
                st.info(
                    "💡 **Informasi:** Berkas **Master Sekolah** (`sekolah`) belum diunggah atau "
                    "data peserta belum diproses ke database MySQL."
                )
                return

        if "kode_sekolah" not in df_master.columns:
            for alt_k in ["npsn", "_school_key", "NPSN", "kode_lembaga"]:
                if alt_k in df_master.columns:
                    df_master["kode_sekolah"] = df_master[alt_k]
                    break

        if "nama_sekolah" not in df_master.columns:
            for alt_n in ["sekolah", "nama_lembaga", "Nama_Sekolah", "NAMA_SEKOLAH"]:
                if alt_n in df_master.columns:
                    df_master["nama_sekolah"] = df_master[alt_n]
                    break

        df_master["kode_sekolah"] = df_master.get("kode_sekolah", df_master.get("_school_key", "-")).fillna("-").astype(str).str.strip()
        df_master["nama_sekolah"] = df_master.get("nama_sekolah", df_master["kode_sekolah"]).fillna(df_master["kode_sekolah"]).astype(str).str.strip()
        df_master["nama_kabupaten"] = df_master.get("nama_kabupaten", df_master.get("kabupaten", "-")).fillna("-").astype(str).str.strip()
        df_master["nama_provinsi"] = df_master.get("nama_provinsi", df_master.get("provinsi", "-")).fillna("-").astype(str).str.strip()
        df_master["kode_provinsi"] = df_master.get("kode_provinsi", df_master.get("kd_prop", "-")).fillna("-").astype(str).str.strip()

        available_mapels = []
        if "mapel" in df_master.columns:
            available_mapels = sorted([
                str(m).strip() for m in df_master["mapel"].dropna().unique()
                if str(m).strip() not in ["", "nan", "None", "-"]
            ])

        df_filtered_school = df_master.copy()
        if available_mapels:
            st.markdown("#### 📚 Filter & Penggabungan Mata Pelajaran")
            selected_mapels = st.multiselect(
                "Pilih Mata Pelajaran (Bisa memilih lebih dari 1 untuk analisis gabungan):",
                options=available_mapels,
                default=available_mapels,
                key="filter_school_mapel_multi",
            )
            if not selected_mapels:
                st.warning("⚠️ Silakan pilih setidaknya satu mata pelajaran untuk dianalisis.")
                return
            df_filtered_school = df_filtered_school[df_filtered_school["mapel"].isin(selected_mapels)].copy()

        available_methods = {}
        if "skor_konversi_ctt" in df_master.columns:
            available_methods["Nilai Konversi (Klasik/CTT)"] = "skor_konversi_ctt"
        if "skor_konversi_rasch" in df_master.columns:
            available_methods["Nilai Konversi (IRT - Rasch/1PL)"] = "skor_konversi_rasch"
        if "skor_konversi_2pl" in df_master.columns:
            available_methods["Nilai Konversi (IRT - 2PL)"] = "skor_konversi_2pl"
        if "skor_konversi_3pl" in df_master.columns:
            available_methods["Nilai Konversi (IRT - 3PL)"] = "skor_konversi_3pl"
        if not available_methods and "skor_mentah" in df_master.columns:
            available_methods["Skor Mentah (Klasik/CTT)"] = "skor_mentah"

        if not available_methods:
            st.error("❌ Tidak ditemukan kolom nilai konversi yang dapat dianalisis.")
            return

        st.markdown("#### ⚙️ Pengaturan Metode Analisis")
        selected_method_label = st.radio(
            "Pilih Metode & Metrik Nilai yang Ingin Dianalisis:",
            options=list(available_methods.keys()),
            horizontal=True,
            key="radio_sekolah_method",
        )
        selected_metric_col = available_methods[selected_method_label]

        st.markdown("#### 🔍 Filter Wilayah & Jumlah Peserta")
        col_f1, col_f2 = st.columns(2)
        prov_dict = {}
        for _, row in df_master[["kode_provinsi", "nama_provinsi"]].dropna().drop_duplicates().iterrows():
            kd_str = str(row["kode_provinsi"]).strip().replace(".0", "").zfill(2)
            nm_str = str(row["nama_provinsi"]).strip().upper()
            if kd_str not in ["-", ""] and nm_str not in ["-", ""]:
                prov_dict[kd_str] = nm_str
        prov_options = [f"{k} - {v}" for k, v in sorted(prov_dict.items())]

        with col_f1:
            selected_prov_options = st.multiselect(
                "Filter Berdasarkan Provinsi (Kode - Nama Provinsi):",
                options=prov_options,
                default=[],
                key="filter_provinsi_single",
            )
        with col_f2:
            min_peserta = st.number_input(
                "Minimal Jumlah Peserta:",
                min_value=1,
                value=1,
                step=1,
                key="filter_min_peserta",
            )

        if selected_prov_options:
            selected_codes = [opt.split(" - ")[0].strip() for opt in selected_prov_options]
            df_filtered_school["_kd_prop_clean"] = df_filtered_school["kode_provinsi"].astype(str).str.strip().str.replace(".0", "", regex=False).str.zfill(2)
            df_filtered_school = df_filtered_school[df_filtered_school["_kd_prop_clean"].isin(selected_codes)]

        df_filtered_school[selected_metric_col] = pd.to_numeric(df_filtered_school[selected_metric_col], errors="coerce")
        id_user_col = "username" if "username" in df_filtered_school.columns else df_filtered_school.columns[0]
        col_sek_kd = "kode_sekolah" if "kode_sekolah" in df_filtered_school.columns else "_school_key"
        group_cols = [col_sek_kd, "nama_sekolah", "nama_kabupaten", "nama_provinsi"]

        df_valid_scores = df_filtered_school.dropna(subset=[selected_metric_col]).copy()
        student_cols = [id_user_col, col_sek_kd, "nama_sekolah", "nama_kabupaten", "nama_provinsi"]
        df_student_composite = df_valid_scores.groupby(student_cols, as_index=False).agg({selected_metric_col: "mean"})
        df_school_summary = df_student_composite.groupby(group_cols, as_index=False).agg(
            Jumlah_Peserta=(id_user_col, "count"),
            Rata_Rata=(selected_metric_col, "mean"),
            Nilai_Min=(selected_metric_col, "min"),
            Nilai_Max=(selected_metric_col, "max"),
            Std_Deviasi=(selected_metric_col, "std"),
        )
        df_school_summary = df_school_summary[df_school_summary["Jumlah_Peserta"] >= min_peserta].copy()

    if df_school_summary.empty:
        st.warning(f"⚠️ Tidak ada sekolah yang memiliki jumlah peserta minimal {min_peserta}. Coba turunkan nilai filter minimal peserta.")
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